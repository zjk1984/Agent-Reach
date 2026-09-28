# -*- coding: utf-8
"""Shared portfolio / symbol helpers for daily-run modules."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code


@dataclass
class EnrichedSymbolProfile:
    """Standardized multi-phase unified symbol profile contract.

    Aggregates D1~D6 attributes across the stock lifecycle:
    selection -> backtesting -> monitoring -> post-market review.
    """
    code: str
    name: str = ""
    is_holding: bool = False
    shares: int = 0
    cost: float = 0.0
    days_held: int = 0

    # D1 + D4: Live quotes & technicals
    price: float = 0.0
    change_pct: float = 0.0
    volume: Optional[float] = None
    turnover: Optional[float] = None
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    position_20d: Optional[float] = None

    # D2: 9:25 Call auction imbalance
    auction_ratio_pct: float = 0.0
    open_pct: float = 0.0
    is_weak_to_strong: bool = False
    is_panic_dumping: bool = False

    # D3: Ladder & Mainline
    consecutive_boards: int = 0
    mainline_sector: str = ""
    mainline_score: float = 0.0
    ladder_fault_status: str = "healthy"

    # D6: Abnormal move price deviation
    cumulative_3d_pct: float = 0.0
    threshold_3d_pct: float = 20.0
    distance_to_limit_pct: float = 20.0
    deviation_risk_level: str = "safe"

    # Decision telemetry
    mss_score: float = 50.0
    verdict: str = "观望"
    blocked_kind: Optional[str] = None
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, code: str, row: dict[str, Any]) -> EnrichedSymbolProfile:
        """Build profile from a loose enriched row dict."""
        data = dict(row or {})
        return cls(
            code=_normalize_code(code),
            name=str(data.get("name") or ""),
            is_holding=bool(data.get("is_holding")),
            shares=int(data.get("shares") or 0),
            cost=float(data.get("cost") or 0.0),
            days_held=int(data.get("days_held") or 0),
            price=float(data.get("price") or 0.0),
            change_pct=float(data.get("change_pct") or 0.0),
            volume=data.get("volume"),
            turnover=data.get("turnover"),
            ma5=data.get("ma5"),
            ma20=data.get("ma20"),
            position_20d=data.get("position_20d"),
            auction_ratio_pct=float(data.get("auction_ratio_pct") or 0.0),
            open_pct=float(data.get("open_pct") or 0.0),
            is_weak_to_strong=bool(data.get("is_weak_to_strong")),
            is_panic_dumping=bool(data.get("is_panic_dumping")),
            consecutive_boards=int(data.get("consecutive_boards") or data.get("consecutive_limit_ups") or 0),
            mainline_sector=str(data.get("mainline_sector") or data.get("sector") or ""),
            mainline_score=float(data.get("mainline_score") or 0.0),
            ladder_fault_status=str(data.get("ladder_fault_status") or "healthy"),
            cumulative_3d_pct=float(data.get("cumulative_3d_pct") or 0.0),
            threshold_3d_pct=float(data.get("threshold_3d_pct") or 20.0),
            distance_to_limit_pct=float(data.get("distance_to_limit_pct") or 20.0),
            deviation_risk_level=str(data.get("deviation_risk_level") or data.get("risk_level") or "safe"),
            mss_score=float(data.get("mss_score") or data.get("mss_final") or 50.0),
            verdict=str(data.get("verdict") or "观望"),
            blocked_kind=data.get("blocked_kind"),
            blocked_reason=str(data.get("blocked_reason") or ""),
        )


ENRICHED_REPLAY_FIELDS: tuple[str, ...] = (
    "price", "change_pct", "ma5", "ma20", "position_20d", "volume", "turnover",
    "auction_ratio_pct", "open_pct", "is_weak_to_strong", "is_panic_dumping",
    "consecutive_boards", "consecutive_limit_ups", "mainline_sector", "mainline_score",
    "ladder_fault_status", "cumulative_3d_pct", "threshold_3d_pct", "distance_to_limit_pct",
    "deviation_risk_level", "risk_level", "industry", "sector",
)


def merge_enriched_row(base: dict[str, Any], enriched_row: dict[str, Any]) -> dict[str, Any]:
    """Merge enriched D1~D6 fields into a target dict without overwriting with None."""
    out = dict(base)
    for key in ENRICHED_REPLAY_FIELDS:
        if key in enriched_row and enriched_row[key] is not None:
            out[key] = enriched_row[key]
    return out


def apply_enriched_replay_context(
    entry: dict[str, Any],
    snapshot: dict[str, Any],
    enriched_map: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Inject unified enriched profile into snapshot/report for intraday replay."""
    code = _normalize_code(str(entry.get("code") or snapshot.get("code") or ""))
    row = dict(enriched_map.get(code) or {})
    payload = entry.get("enriched") or entry.get("symbol_profile") or {}
    if isinstance(payload, dict):
        row = {**row, **payload}

    snap = dict(snapshot)
    snap["code"] = code
    snap["name"] = entry.get("name") or snap.get("name") or row.get("name") or code
    for key in ENRICHED_REPLAY_FIELDS:
        if key in row and row[key] is not None:
            snap[key] = row[key]

    report = merge_enriched_row(
        {
            "code": code,
            "name": snap.get("name"),
            "verdict": entry.get("verdict"),
            "mss_final": entry.get("mss_final"),
            "reasoning": entry.get("reasoning"),
        },
        row,
    )
    return snap, report


def build_scan_enriched_payload(
    code: str,
    enriched_snapshot: dict[str, Any],
    entry: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build EnrichedSymbolProfile dict for persisting into l0_events intraday_scan."""
    sym = _normalize_code(code)
    enriched_map = build_enriched_symbols(enriched_snapshot, settings=settings)
    row = dict(enriched_map.get(sym) or {})
    row.setdefault("code", sym)
    row["name"] = str(entry.get("name") or row.get("name") or sym)
    if entry.get("mss_final") is not None:
        row["mss_score"] = float(entry["mss_final"])
    if entry.get("verdict"):
        row["verdict"] = str(entry["verdict"])
    if entry.get("price") is not None:
        row["price"] = float(entry["price"])
    return EnrichedSymbolProfile.from_dict(sym, row).to_dict()


def copy_portfolio(portfolio: dict[str, Any]) -> dict[str, Any]:
    pf = dict(portfolio)
    pf["holdings"] = [dict(h) for h in (portfolio.get("holdings") or [])]
    pf["watchlist"] = [dict(w) for w in (portfolio.get("watchlist") or [])]
    return pf


def build_enriched_symbols(
    snapshot: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge holdings + watchlist + primary code from snapshot into one map with D1~D6 metrics."""
    out: dict[str, dict[str, Any]] = {}
    for h in (snapshot.get("portfolio") or {}).get("holdings") or []:
        code = _normalize_code(str(h.get("code", "")))
        if code:
            row = dict(h)
            row["is_holding"] = True
            out[code] = row
    for w in snapshot.get("watchlist") or []:
        code = _normalize_code(str(w.get("code", "")))
        if code:
            row = dict(w)
            if code in out:
                out[code] = {**out[code], **row}
            else:
                row["is_holding"] = False
                out[code] = row
    code = snapshot.get("code")
    if code:
        c = _normalize_code(str(code))
        out[c] = {
            **out.get(c, {}),
            **{
                k: snapshot[k]
                for k in (
                    "price", "name", "change_pct", "ma20", "ma5", "sector", "industry",
                    "volume", "turnover", "position_20d", "consecutive_limit_ups",
                    "consecutive_boards", "auction_ratio_pct", "open_pct",
                    "is_weak_to_strong", "is_panic_dumping", "distance_to_limit_pct",
                    "cumulative_3d_pct", "threshold_3d_pct", "risk_level"
                )
                if k in snapshot and snapshot[k] is not None
            },
        }

    cfg = settings
    if cfg is None:
        try:
            from agent_reach.daily_run.settings import load_settings

            cfg = load_settings()
        except Exception:
            cfg = None

    # Harmonize D1~D6 attributes across all symbols
    for s_code, row in out.items():
        # Ensure default D2/D3/D6 keys exist
        if "is_holding" not in row:
            row["is_holding"] = False
        if "consecutive_boards" not in row:
            row["consecutive_boards"] = int(row.get("consecutive_limit_ups") or 0)

        # Call Auction Sentinel alignment (D2)
        if "is_weak_to_strong" not in row or "is_panic_dumping" not in row:
            try:
                from agent_reach.daily_run.tsp.call_auction import evaluate_call_auction_divergence
                auc = evaluate_call_auction_divergence(s_code, symbol_data=row, settings=cfg)
                row["is_weak_to_strong"] = auc.get("is_weak_to_strong", False)
                row["is_panic_dumping"] = auc.get("is_panic_dumping", False)
                row["auction_ratio_pct"] = auc.get("auction_ratio_pct", 0.0)
            except Exception:
                pass

        # Deviation Risk alignment (D6)
        if "distance_to_limit_pct" not in row:
            try:
                from agent_reach.daily_run.tsp.deviation_monitor import compute_exchange_deviation_risk
                dev = compute_exchange_deviation_risk(row)
                row["distance_to_limit_pct"] = dev.get("distance_to_limit_pct", 20.0)
                row["cumulative_3d_pct"] = dev.get("cumulative_3d_pct", 0.0)
                row["threshold_3d_pct"] = dev.get("threshold_3d_pct", 20.0)
                row["deviation_risk_level"] = dev.get("risk_level", "safe")
            except Exception:
                pass

    if cfg:
        from agent_reach.daily_run.bar_alignment import annotate_enriched_bar_quality
        from agent_reach.daily_run.sector_classifier import enrich_symbol_map_sectors

        out = enrich_symbol_map_sectors(out, cfg)
        out = annotate_enriched_bar_quality(out, settings=cfg)
    return out


def portfolio_from_snapshot(enriched: dict[str, Any]) -> dict[str, Any]:
    """Rebuild portfolio dict from enriched snapshot (avoids extra disk read)."""
    block = enriched.get("portfolio") or {}
    return {
        "total": block.get("total"),
        "cash": block.get("cash"),
        "cash_ratio": block.get("cash_ratio"),
        "holdings": [dict(h) for h in (block.get("holdings") or [])],
        "watchlist": [dict(w) for w in (enriched.get("watchlist") or [])],
    }


def sync_snapshot_portfolio(snapshot: dict[str, Any], portfolio: dict[str, Any]) -> None:
    """Apply portfolio.json fields onto snapshot blocks in-place."""
    snapshot["watchlist"] = list(portfolio.get("watchlist") or [])
    block = dict(snapshot.get("portfolio") or {})
    for key in ("holdings", "cash", "cash_ratio", "total"):
        if key in portfolio:
            block[key] = portfolio[key]
    snapshot["portfolio"] = block


def list_target_symbols(
    portfolio: dict[str, Any],
    *,
    mode: str = "all",
) -> list[str]:
    """Return ordered unique symbol codes from portfolio.

    mode:
      - all: holdings then watchlist (deduped)
      - holdings: holdings only
      - watchlist: watchlist only
    """
    codes: list[str] = []
    seen: set[str] = set()

    def _add(items: list[dict[str, Any]]) -> None:
        for row in items:
            code = _normalize_code(str(row.get("code", "")))
            if code and code not in seen:
                seen.add(code)
                codes.append(code)

    if mode in ("all", "holdings"):
        _add(list(portfolio.get("holdings") or []))
    if mode in ("all", "watchlist"):
        _add(list(portfolio.get("watchlist") or []))
    return codes


def resolve_target_symbols(
    portfolio: dict[str, Any],
    settings: dict[str, Any],
    *,
    workflow: str | None = None,
) -> list[str]:
    """Resolve which symbols to run for morning/close/intraday jobs.

    intraday_symbols_mode (when workflow=intraday):
      - all / holdings+watchlist: 持仓 + 观察池（去重）
      - holdings: 仅持仓
      - watchlist: 仅观察池
      - primary: 主标的
    close_symbols_mode (when workflow=close):
      - same values as intraday; defaults to schedule.symbols_mode when unset
    Falls back to schedule.symbols_mode when workflow-specific mode is unset.
    """
    sched = settings.get("schedule") or {}
    if workflow == "intraday":
        mode = str(
            sched.get("intraday_symbols_mode") or sched.get("symbols_mode", "primary")
        ).lower()
        # Shorthand: scan holdings + 观察池 (same as mode=all, excludes duplicate codes)
        if mode in ("holdings+watchlist", "holdings_watchlist"):
            mode = "all"
    elif workflow == "close":
        mode = str(
            sched.get("close_symbols_mode") or sched.get("symbols_mode", "primary")
        ).lower()
        if mode in ("holdings+watchlist", "holdings_watchlist"):
            mode = "all"
    else:
        mode = str(sched.get("symbols_mode", "primary")).lower()
    if mode == "primary":
        code = portfolio.get("primary_code")
        if not code and portfolio.get("holdings"):
            code = portfolio["holdings"][0]["code"]
        if code:
            return [_normalize_code(str(code))]
        return ["MARKET"]
    return list_target_symbols(portfolio, mode=mode)


def is_redundant_symbol_name(name: Any, code: str) -> bool:
    """True when *name* adds no information beyond the normalized code."""
    norm = _normalize_code(code)
    if not name or not str(name).strip():
        return True
    text = str(name).strip()
    if _normalize_code(text) == norm:
        return True
    compact = text.replace(" ", "")
    return compact in {norm, f"{norm}({norm})", f"{norm}（{norm}）"}


def _portfolio_rows(
    portfolio: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if portfolio:
        rows.extend(list(portfolio.get("holdings") or []))
        rows.extend(list(portfolio.get("watchlist") or []))
    if snapshot:
        block = snapshot.get("portfolio") or {}
        rows.extend(list(block.get("holdings") or []))
        rows.extend(list(snapshot.get("watchlist") or []))
    return rows


def resolve_symbol_name(
    portfolio: dict[str, Any] | None,
    code: str,
    *,
    fallback: Any = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Resolve a human-readable symbol name; never return code duplicated as name."""
    norm = _normalize_code(code)
    for row in _portfolio_rows(portfolio, snapshot=snapshot):
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        row_name = row.get("name")
        if row_name and not is_redundant_symbol_name(row_name, norm):
            return str(row_name).strip()
    if fallback is not None and not is_redundant_symbol_name(fallback, norm):
        return str(fallback).strip()
    return norm


def format_symbol_reference(
    name: Any,
    code: str,
    *,
    portfolio: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Display label like 水晶光电(002273); omit parens when only the code is known."""
    norm = _normalize_code(code)
    resolved = resolve_symbol_name(portfolio, norm, fallback=name, snapshot=snapshot)
    if is_redundant_symbol_name(resolved, norm):
        return norm
    return f"{resolved}({norm})"


def symbol_display_name(
    portfolio: dict[str, Any],
    code: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Best-effort name lookup from portfolio rows."""
    return resolve_symbol_name(portfolio, code, snapshot=snapshot)
