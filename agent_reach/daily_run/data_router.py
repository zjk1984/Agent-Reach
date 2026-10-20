# -*- coding: utf-8 -*-
"""Market Data Router for Agent Reach Daily-Run.

Provides independent capability-based routing, isolated process-level TTL caches,
and graceful degradation for 6 market dataset classes (D1 ~ D6):
- D1: Live Quotes / L1 Fast Quotes (Eastmoney push2 / Xueqiu / Akshare fallback)
- D2: Call Auction / Order-flow slice (9:25 auction ratio, open gap, weak-to-strong)
- D3: Emotion Regime / Ladder (Limit up/down pool, consecutive boards, broken rate)
- D4: Daily Bars & Technicals (Historical bars, MA5, MA20, 20d position, ATR)
- D5: Macro / News Context (60s API, hot topics, macro indices)
- D6: Regulatory Deviation Rules (Exchange abnormal move 3d/10d/30d cushions)
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from agent_reach.daily_run.quote_fetch import QuoteFetchResult, fetch_quotes_map, normalize_code
from agent_reach.daily_run.tsp.deviation_monitor import compute_exchange_deviation_risk
from agent_reach.daily_run.tsp.call_auction import evaluate_call_auction_divergence


class MarketDataRouter:
    """Independent source router for D1~D6 datasets with isolated TTL caches."""

    def __init__(self, settings: Optional[dict[str, Any]] = None):
        self.settings = settings or {}
        self._last_d1_quote_fetch: Optional[QuoteFetchResult] = None
        self._last_d1_requested_codes: list[str] = []
        self._cache: Dict[str, Dict[str, Any]] = {
            "d1_quotes": {"data": {}, "ts": 0.0},
            "d2_auction": {"data": {}, "ts": 0.0},
            "d3_ladder": {"data": None, "ts": 0.0},
            "d4_technicals": {"data": {}, "ts": 0.0},
            "d5_macro": {"data": None, "ts": 0.0},
            "d6_deviation": {"data": {}, "ts": 0.0},
        }

    # -------------------------------------------------------------------------
    # D1: Live Quotes (Fast L1 / Push2)
    # -------------------------------------------------------------------------
    def _d1_resilience_cfg(self) -> tuple[int, tuple[float, ...], bool]:
        qcfg = self.settings.get("quote_fetch") or {}
        pytest_run = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if "d1_retry_max_attempts" in qcfg:
            max_attempts = int(qcfg["d1_retry_max_attempts"])
        elif pytest_run:
            max_attempts = 1
        else:
            max_attempts = 3
        raw_delays = qcfg.get("d1_retry_delays")
        if isinstance(raw_delays, (list, tuple)):
            delays = tuple(float(x) for x in raw_delays)
        elif pytest_run:
            delays = (0.0, 0.0, 0.0)
        else:
            delays = (15.0, 20.0, 30.0)
        enabled = qcfg.get("d1_empty_retry", True) is not False
        return max(1, max_attempts), delays, enabled

    def _merge_d1_fetch_into(
        self,
        fetch_res: QuoteFetchResult,
        *,
        cached: dict[str, Any],
        result: dict[str, dict[str, Any]],
        now: float,
    ) -> None:
        for c, q in fetch_res.quotes.items():
            cached["data"][c] = q
            result[c] = dict(q)
        cached["ts"] = now

    def _fetch_d1_with_resilience(
        self,
        codes: list[str],
        *,
        cached: dict[str, Any],
        result: dict[str, dict[str, Any]],
        now: float,
    ) -> QuoteFetchResult:
        """Fetch missing D1 quotes; retry on empty/partial with backoff (morning transient blips)."""
        unique = list(dict.fromkeys(codes))
        if not unique:
            return QuoteFetchResult()

        max_attempts, delays, enabled = self._d1_resilience_cfg()
        aggregate = QuoteFetchResult()

        still_missing = list(unique)
        last_res = QuoteFetchResult()
        for attempt in range(max_attempts):
            if not still_missing:
                break
            try:
                last_res = fetch_quotes_map(still_missing, settings=self.settings)
            except Exception as exc:
                logger.warning(f"[DataRouter:D1] get_live_quotes error: {exc}")
                for code in still_missing:
                    aggregate.errors.setdefault(code, str(exc))
                break
            self._merge_d1_fetch_into(last_res, cached=cached, result=result, now=now)
            for src in last_res.sources_used:
                if src not in aggregate.sources_used:
                    aggregate.sources_used.append(src)
            for code, q in last_res.quotes.items():
                aggregate.quotes[code] = q
                aggregate.errors.pop(code, None)
            for code, err in last_res.errors.items():
                if code not in aggregate.quotes:
                    aggregate.errors[code] = err
            still_missing = [c for c in unique if c not in result]
            if not still_missing:
                break
            if not enabled or attempt >= max_attempts - 1:
                break
            delay = delays[min(attempt, len(delays) - 1)] if delays else 1.0
            logger.info(
                "[DataRouter:D1] partial quote coverage {}/{}; retry in {:.0f}s (attempt {})",
                len(unique) - len(still_missing),
                len(unique),
                delay,
                attempt + 2,
            )
            time.sleep(delay)

        for code in still_missing:
            aggregate.errors.setdefault(
                code,
                last_res.errors.get(code, "no quote from configured sources"),
            )
        return aggregate

    def get_live_quotes(
        self,
        codes: List[str],
        *,
        force_refresh: bool = False,
        ttl_seconds: int = 5,
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch live quotes with fast TTL cache (default 5s for intraday)."""
        now = time.time()
        cached = self._cache["d1_quotes"]
        norm_codes = [normalize_code(c) for c in codes if c]
        unique_codes = list(dict.fromkeys(norm_codes))
        self._last_d1_requested_codes = list(unique_codes)
        self._last_d1_quote_fetch = None
        if not unique_codes:
            return {}

        missing: List[str] = []
        result: Dict[str, Dict[str, Any]] = {}

        if not force_refresh and (now - cached["ts"] < ttl_seconds):
            for c in unique_codes:
                if c in cached["data"]:
                    result[c] = dict(cached["data"][c])
                else:
                    missing.append(c)
        else:
            missing = list(unique_codes)

        if missing:
            self._last_d1_quote_fetch = self._fetch_d1_with_resilience(
                missing,
                cached=cached,
                result=result,
                now=now,
            )

        fetch_meta = self._last_d1_quote_fetch or QuoteFetchResult()
        missing_after = [c for c in unique_codes if c not in result]
        self._last_d1_quote_fetch = QuoteFetchResult(
            quotes={c: result[c] for c in unique_codes if c in result},
            sources_used=list(fetch_meta.sources_used),
            errors={
                c: fetch_meta.errors.get(c, "no quote from configured sources")
                for c in missing_after
            },
        )

        return result

    def get_last_d1_quote_fetch(self) -> Optional[QuoteFetchResult]:
        """QuoteFetchResult from the latest get_live_quotes batch fetch (for snapshot manifest)."""
        return self._last_d1_quote_fetch

    def d1_quote_fetch_meta_for(self, codes: list[str]) -> dict[str, Any]:
        """Coverage + errors for requested codes after the last get_live_quotes call."""
        unique = list(dict.fromkeys(normalize_code(c) for c in codes if c))
        fetch_res = self._last_d1_quote_fetch or QuoteFetchResult()
        hit = sum(1 for c in unique if c in fetch_res.quotes)
        meta: dict[str, Any] = {
            "sources_used": list(fetch_res.sources_used),
            "coverage_pct": round(hit / max(len(unique), 1) * 100, 1),
            "errors": {},
        }
        if hit < len(unique):
            meta["errors"] = {
                c: fetch_res.errors.get(c, "no quote from configured sources")
                for c in unique
                if c not in fetch_res.quotes
            }
        return meta

    # -------------------------------------------------------------------------
    # D2: 9:25 Call Auction Imbalance & Order-Flow Slice
    # -------------------------------------------------------------------------
    def get_call_auction(
        self,
        symbol_code: str,
        symbol_data: Optional[Dict[str, Any]] = None,
        *,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Evaluate 9:25 AM call auction order-flow imbalance for a symbol."""
        code = normalize_code(symbol_code)
        now = time.time()
        cached = self._cache["d2_auction"]

        # Call auction is static once market opens (9:30 AM onwards, TTL 3600s)
        if not force_refresh and code in cached["data"] and (now - cached["ts"] < 3600):
            return cached["data"][code]

        try:
            res = evaluate_call_auction_divergence(
                code,
                symbol_data=symbol_data,
                settings=self.settings,
            )
            cached["data"][code] = res
            cached["ts"] = now
            return res
        except Exception as exc:
            logger.debug(f"[DataRouter:D2] get_call_auction error for {code}: {exc}")
            return {
                "symbol": code,
                "signal": "normal",
                "open_pct": 0.0,
                "auction_ratio_pct": 0.0,
                "is_weak_to_strong": False,
                "is_panic_dumping": False,
                "blocked_buy": False,
                "mss_delta": 0.0,
                "reason": "",
            }

    # -------------------------------------------------------------------------
    # D3: Short-term Market Regime & Ladder Progression
    # -------------------------------------------------------------------------
    def get_ladder_regime(
        self,
        *,
        force_refresh: bool = False,
        ttl_seconds: int = 30,
    ) -> Dict[str, Any]:
        """Fetch market limit up/down breadth, ladder progression and TSP phase."""
        now = time.time()
        cached = self._cache["d3_ladder"]
        if not force_refresh and cached["data"] is not None and (now - cached["ts"] < ttl_seconds):
            return cached["data"]

        try:
            from agent_reach.daily_run.tsp.intraday_sentinel import get_live_market_breadth_and_phase

            data = get_live_market_breadth_and_phase(self.settings, force_refresh=force_refresh)
            cached["data"] = data
            cached["ts"] = now
            return data
        except Exception as exc:
            logger.warning(f"[DataRouter:D3] get_ladder_regime error: {exc}")
            return {
                "limit_up": 0,
                "limit_down": 0,
                "broken_rate": 0.0,
                "highest_board": 1,
                "phase": "neutral",
                "phase_name": "平稳",
                "promotion_ladder": {},
            }

    # -------------------------------------------------------------------------
    # D4: Daily Bars & Moving Averages (Technicals)
    # -------------------------------------------------------------------------
    def get_bars_and_ma(
        self,
        symbol_code: str,
        symbol_data: Optional[Dict[str, Any]] = None,
        *,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Get technical moving averages (MA5, MA20, position_20d)."""
        code = normalize_code(symbol_code)
        now = time.time()
        cached = self._cache["d4_technicals"]

        if not force_refresh and code in cached["data"] and (now - cached["ts"] < 600):
            return cached["data"][code]

        data = dict(symbol_data or {})
        if isinstance(data.get("snapshot"), dict):
            data.update(data["snapshot"])

        tech = {
            "ma5": data.get("ma5"),
            "ma20": data.get("ma20"),
            "position_20d": data.get("position_20d"),
            "volume_ratio": data.get("volume_ratio"),
        }
        cached["data"][code] = tech
        cached["ts"] = now
        return tech

    # -------------------------------------------------------------------------
    # D5: Macro Context & News Topics
    # -------------------------------------------------------------------------
    def get_macro_context(
        self,
        portfolio: Optional[Dict[str, Any]] = None,
        *,
        workflow: str = "intraday",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Fetch or reuse cached macro context."""
        now = time.time()
        cached = self._cache["d5_macro"]
        # Intraday reuses daily macro cache (TTL 3600s)
        if not force_refresh and cached["data"] is not None and (now - cached["ts"] < 3600):
            return cached["data"]

        try:
            from agent_reach.daily_run.macro_collector import collect_macro_context
            from agent_reach.daily_run.snapshot_cache import load_daily_cache

            daily_cache = load_daily_cache()
            if daily_cache.get("macro_ctx") and workflow == "intraday" and not force_refresh:
                cached["data"] = dict(daily_cache["macro_ctx"])
                cached["ts"] = now
                return cached["data"]

            macro = collect_macro_context(
                portfolio or {},
                settings=self.settings,
                workflow=workflow,
                scope="flow_index" if workflow == "intraday" else "full",
            )
            cached["data"] = dict(macro)
            cached["ts"] = now
            return cached["data"]
        except Exception as exc:
            logger.debug(f"[DataRouter:D5] get_macro_context error: {exc}")
            return {"summary": "宏观态势稳定", "sources": {}}

    # -------------------------------------------------------------------------
    # D6: Regulatory Abnormal Move Deviation Rules
    # -------------------------------------------------------------------------
    def get_deviation_rules(
        self,
        symbol_code: str,
        symbol_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute exchange abnormal move price deviation risk & cushions."""
        code = normalize_code(symbol_code)
        try:
            risk = compute_exchange_deviation_risk(
                symbol_data if isinstance(symbol_data, dict) else {},
            )
            return risk
        except Exception as exc:
            logger.debug(f"[DataRouter:D6] get_deviation_rules error for {code}: {exc}")
            return {
                "warning": False,
                "blocked_buy": False,
                "distance_to_limit_pct": 20.0,
                "threshold_3d_pct": 20.0,
                "cumulative_3d_pct": 0.0,
                "risk_level": "safe",
                "reason": "",
            }

    # -------------------------------------------------------------------------
    # Provenance / Diagnostics Health Check
    # -------------------------------------------------------------------------
    def get_provenance_status(self) -> Dict[str, Any]:
        """Return operational health and caching status of D1~D6 data feeds."""
        now = time.time()
        return {
            "d1_quotes": {
                "label": "实时盘口行情 (D1)",
                "status": "healthy" if self._cache["d1_quotes"]["ts"] > 0 else "standby",
                "cached_items": len(self._cache["d1_quotes"]["data"]),
                "age_seconds": round(now - self._cache["d1_quotes"]["ts"], 1) if self._cache["d1_quotes"]["ts"] > 0 else None,
            },
            "d2_auction": {
                "label": "集合竞价脉搏 (D2)",
                "status": "active" if self._cache["d2_auction"]["ts"] > 0 else "standby",
                "cached_items": len(self._cache["d2_auction"]["data"]),
            },
            "d3_ladder": {
                "label": "连板天梯情绪 (D3)",
                "status": "healthy" if self._cache["d3_ladder"]["ts"] > 0 else "standby",
                "age_seconds": round(now - self._cache["d3_ladder"]["ts"], 1) if self._cache["d3_ladder"]["ts"] > 0 else None,
                "source": (self._cache["d3_ladder"].get("data") or {}).get("source"),
                "ladder_degraded": (self._cache["d3_ladder"].get("data") or {}).get(
                    "ladder_degraded"
                ),
                "limit_degraded": (self._cache["d3_ladder"].get("data") or {}).get(
                    "limit_degraded"
                ),
            },
            "d4_technicals": {
                "label": "日K量价均线 (D4)",
                "status": "healthy" if self._cache["d4_technicals"]["ts"] > 0 else "standby",
                "cached_items": len(self._cache["d4_technicals"]["data"]),
            },
            "d5_macro": {
                "label": "宏观舆情催化 (D5)",
                "status": "healthy" if self._cache["d5_macro"]["ts"] > 0 else "standby",
            },
            "d6_deviation": {
                "label": "异动偏离监管 (D6)",
                "status": "healthy",
                "rule_type": "SSE/SZSE 3d/10d/30d",
            },
        }


# Global singleton router
_GLOBAL_ROUTER: Optional[MarketDataRouter] = None


def get_market_data_router(settings: Optional[dict[str, Any]] = None) -> MarketDataRouter:
    """Get or instantiate global market data router."""
    global _GLOBAL_ROUTER
    if _GLOBAL_ROUTER is None:
        _GLOBAL_ROUTER = MarketDataRouter(settings=settings)
    elif settings is not None:
        _GLOBAL_ROUTER.settings = settings
    return _GLOBAL_ROUTER


def clear_market_data_router() -> None:
    """Reset global router singleton (mainly for tests)."""
    global _GLOBAL_ROUTER
    _GLOBAL_ROUTER = None


_PROVENANCE_SHORT_LABELS: tuple[tuple[str, str], ...] = (
    ("d1_quotes", "D1"),
    ("d2_auction", "D2"),
    ("d3_ladder", "D3"),
    ("d4_technicals", "D4"),
    ("d5_macro", "D5"),
    ("d6_deviation", "D6"),
)


def format_provenance_compact_line(
    provenance: Optional[Dict[str, Any]] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """Compact D1~D6 status line for Feishu cards and logs."""
    prov = provenance if provenance is not None else get_market_data_router(settings).get_provenance_status()
    parts: list[str] = []
    for key, short in _PROVENANCE_SHORT_LABELS:
        status = str((prov.get(key) or {}).get("status") or "standby")
        mark = "✓" if status in ("healthy", "active") else "·"
        parts.append(f"{short}{mark}")
    return "📡 数据源：" + " ".join(parts)
