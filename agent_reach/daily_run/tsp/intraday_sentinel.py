# -*- coding: utf-8 -*-
"""TSP Intraday Sentinel & Mainline Quant Matcher.

Provides process-level cached live breadth probing, mainline resonance matching,
non-mainline guards, and intraday retreat detection for daily-run intraday execution.
"""

from __future__ import annotations

import time
from typing import Any, NamedTuple, Optional
from loguru import logger

from agent_reach.daily_run.tsp.config import tsp_quant_cfg
from agent_reach.daily_run.tsp.market_regime import compute_tsp_market_phase
from agent_reach.daily_run.tsp.mainline_ranker import rank_tsp_mainlines


# Process-level cache for live market breadth and sentiment regime
_LIVE_BREADTH_CACHE: dict[str, Any] = {
    "data": None,
    "timestamp": 0.0,
}


def clear_intraday_sentinel_cache() -> None:
    """Clear process-level live breadth cache (mainly for testing)."""
    global _LIVE_BREADTH_CACHE
    _LIVE_BREADTH_CACHE = {
        "data": None,
        "timestamp": 0.0,
    }


class TSPMainlineMatch(NamedTuple):
    """Result of matching a symbol against TSP mainline sectors."""
    is_mainline: bool
    sector_name: str
    score: float
    highest_board: int
    rank: Optional[int] = None


def get_live_market_breadth_and_phase(
    settings: Optional[dict[str, Any]] = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Lightweight probe of intraday market breadth, ladder height, and TSP phase.

    Cached at process level with configurable TTL (default 300 seconds) to prevent
    redundant network requests across multiple scans or symbols.
    """
    global _LIVE_BREADTH_CACHE

    cfg = tsp_quant_cfg(settings)
    intraday_cfg = cfg.get("intraday") or {}
    ttl_seconds = int(intraday_cfg.get("live_breadth_cache_ttl_seconds", 300))

    now = time.time()
    if (
        not force_refresh
        and _LIVE_BREADTH_CACHE["data"] is not None
        and (now - _LIVE_BREADTH_CACHE["timestamp"]) < ttl_seconds
    ):
        return _LIVE_BREADTH_CACHE["data"]

    # Fail-open baseline structure
    fallback_data: dict[str, Any] = {
        "limit_up": 0,
        "limit_up_count": 0,
        "limit_down": 0,
        "limit_down_count": 0,
        "broken_count": 0,
        "broken_rate": 0.0,
        "highest_board": 1,
        "two_board_count": 0,
        "phase": "neutral",
        "phase_name": "未知/平衡",
        "session_regime": "neutral",
        "summary": "TSP 情绪探测：降级模式",
        "top_mainlines": [],
        "limit_up_stocks": [],
        "source": "fallback",
        "cached_at": now,
    }

    if not cfg.get("enabled", True) or not intraday_cfg.get("enabled", True):
        return fallback_data

    try:
        from agent_reach.daily_run.trade_calendar import today_shanghai
        review_date = today_shanghai().isoformat()

        limit_up = 0
        limit_down = 0
        broken_count = 0
        broken_rate = 0.0
        limit_up_stocks: list[dict[str, Any]] = []
        source = "none"

        # 1. Try akshare limit pools first
        try:
            from agent_reach.daily_run.limit_pool_collector import fetch_akshare_limit_pools
            import os

            is_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
            allow_live = bool(os.environ.get("AGENT_REACH_TSP_LIVE"))
            is_mocked = hasattr(fetch_akshare_limit_pools, "mock_calls") or hasattr(
                fetch_akshare_limit_pools, "_mock_return_value"
            )

            if not is_pytest or allow_live or is_mocked:
                pool = fetch_akshare_limit_pools(review_date, include_stocks=True)
                if pool:
                    limit_up = int(pool.get("limit_up") or 0)
                    limit_down = int(pool.get("limit_down") or 0)
                    broken_count = int(pool.get("broken_count") or 0)
                    broken_rate = float(pool.get("broken_rate") or 0.0)
                    limit_up_stocks = list(pool.get("limit_up_stocks") or [])
                    source = str(pool.get("source") or "akshare_pool")
        except Exception as exc:
            logger.debug(f"[TSP Intraday] akshare limit pool fetch failed: {exc}")

        # 2. If akshare failed or empty, fallback to today's market review if loaded
        if not limit_up_stocks and limit_up == 0:
            try:
                from agent_reach.daily_run.market_review import load_market_review
                import os

                is_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
                allow_live = bool(os.environ.get("AGENT_REACH_TSP_LIVE"))
                is_mr_mocked = hasattr(load_market_review, "mock_calls") or hasattr(
                    load_market_review, "_mock_return_value"
                )
                allow_disk = (
                    not is_pytest
                    or allow_live
                    or is_mr_mocked
                    or os.environ.get("AGENT_REACH_TSP_ALLOW_DISK", "").strip().lower()
                    in ("1", "true", "yes")
                )
                if allow_disk:
                    mr = load_market_review(review_date)
                    if mr:
                        em = mr.get("emotion") or {}
                        sa = mr.get("sector_analysis") or {}
                        limit_up = int(em.get("limit_up") or 0)
                        limit_down = int(em.get("limit_down") or 0)
                        broken_count = int(em.get("broken_count") or 0)
                        broken_rate = float(em.get("broken_rate") or 0.0)
                        limit_up_stocks = list(
                            sa.get("limit_up_stocks") or mr.get("limit_up_stocks") or []
                        )
                        source = "market_review"
            except Exception as exc:
                logger.debug(f"[TSP Intraday] market_review load failed: {exc}")

        # 3. Analyze ladder (highest_board and two_board_count)
        highest_board = 1
        two_board_count = 0
        for stock in limit_up_stocks:
            board = stock.get("consecutive_limit_ups")
            if board is None:
                pct = float(stock.get("change_pct") or 0.0)
                board = max(1, int(round(pct / 10))) if pct > 15 else 1
            b_int = int(board)
            highest_board = max(highest_board, b_int)
            if b_int == 2:
                two_board_count += 1

        # 4. Rank mainline sectors
        min_limit_ups = int(cfg.get("mainline_min_limit_ups", 2))
        top_mainlines = rank_tsp_mainlines(
            limit_up_stocks,
            min_limit_ups=min_limit_ups,
            limit=5,
        )

        # 5. Compute market phase
        phase_info = compute_tsp_market_phase(
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            broken_rate=broken_rate,
            highest_board=highest_board,
            two_board_count=two_board_count,
            settings=settings,
        )

        result = {
            "limit_up": limit_up,
            "limit_up_count": limit_up,
            "limit_down": limit_down,
            "limit_down_count": limit_down,
            "broken_count": broken_count,
            "broken_rate": round(broken_rate, 4),
            "highest_board": highest_board,
            "two_board_count": two_board_count,
            "phase": phase_info["phase"],
            "phase_name": phase_info["phase_name"],
            "session_regime": phase_info["session_regime"],
            "summary": phase_info["summary"],
            "top_mainlines": top_mainlines,
            "limit_up_stocks": limit_up_stocks,
            "source": source,
            "cached_at": now,
        }

        _LIVE_BREADTH_CACHE = {
            "data": result,
            "timestamp": now,
        }
        return result

    except Exception as exc:
        logger.warning(f"[TSP Intraday] get_live_market_breadth_and_phase fallback due to error: {exc}")
        return fallback_data


def _extract_symbol_candidates(code: str, symbol_data: Optional[dict[str, Any]]) -> list[str]:
    """Extract possible sector / industry / concept keywords for a symbol."""
    candidates: list[str] = []
    if not symbol_data:
        return candidates

    data = dict(symbol_data)
    # Check nested report or snapshot
    if isinstance(data.get("report"), dict):
        data.update(data["report"])
    if isinstance(data.get("snapshot"), dict):
        data.update(data["snapshot"])

    for key in ("industry", "sector", "concept", "plate", "board_name", "sub_industry"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            for part in val.replace("、", ",").replace(";", ",").replace("/", ",").split(","):
                p = part.strip()
                if p and p not in candidates and p != "其他":
                    candidates.append(p)
        elif isinstance(val, (list, tuple)):
            for item in val:
                p = str(item).strip()
                if p and p not in candidates and p != "其他":
                    candidates.append(p)

    concepts = data.get("concepts")
    if isinstance(concepts, list):
        for item in concepts:
            if isinstance(item, dict):
                p = str(item.get("name") or "").strip()
            else:
                p = str(item).strip()
            if p and p not in candidates and p != "其他":
                candidates.append(p)
    elif isinstance(concepts, str) and concepts.strip():
        for part in concepts.replace("、", ",").replace(";", ",").split(","):
            p = part.strip()
            if p and p not in candidates and p != "其他":
                candidates.append(p)

    return candidates


def match_symbol_tsp_mainline(
    code: str,
    symbol_data: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    *,
    live_breadth: Optional[dict[str, Any]] = None,
) -> TSPMainlineMatch:
    """Match a stock symbol against intraday TSP mainline sectors.

    Returns a TSPMainlineMatch tuple: (is_mainline, sector_name, score, highest_board, rank)
    where is_mainline is True if the symbol belongs to the Top 2 mainline sectors.
    """
    try:
        norm_code = str(code or "").strip().upper()
        for prefix in ("SH", "SZ", "BJ"):
            if norm_code.startswith(prefix):
                norm_code = norm_code[len(prefix):]
                break
        norm_code = norm_code.zfill(6)

        breadth = live_breadth or get_live_market_breadth_and_phase(settings)
        mainlines = breadth.get("top_mainlines") or []
        if not mainlines:
            return TSPMainlineMatch(
                is_mainline=False,
                sector_name="",
                score=0.0,
                highest_board=1,
                rank=None,
            )

        # 1. Direct match by stock code in mainline constituents
        for rank_idx, ml in enumerate(mainlines, start=1):
            stocks = ml.get("stocks") or ml.get("top_stocks") or []
            for s in stocks:
                s_code = str(s.get("code") or "").strip().upper()
                for prefix in ("SH", "SZ", "BJ"):
                    if s_code.startswith(prefix):
                        s_code = s_code[len(prefix):]
                        break
                s_code = s_code.zfill(6)
                if s_code == norm_code:
                    return TSPMainlineMatch(
                        is_mainline=(rank_idx <= 2),
                        sector_name=str(ml.get("sector") or ""),
                        score=float(ml.get("score") or 0.0),
                        highest_board=int(ml.get("highest_board") or 1),
                        rank=rank_idx,
                    )

        # 2. Sector / concept keyword matching
        candidates = _extract_symbol_candidates(norm_code, symbol_data)
        if candidates:
            for rank_idx, ml in enumerate(mainlines, start=1):
                ml_sec = str(ml.get("sector") or "").strip()
                if not ml_sec:
                    continue
                for cand in candidates:
                    if cand == ml_sec or cand in ml_sec or ml_sec in cand:
                        return TSPMainlineMatch(
                            is_mainline=(rank_idx <= 2),
                            sector_name=ml_sec,
                            score=float(ml.get("score") or 0.0),
                            highest_board=int(ml.get("highest_board") or 1),
                            rank=rank_idx,
                        )

        return TSPMainlineMatch(
            is_mainline=False,
            sector_name="",
            score=0.0,
            highest_board=1,
            rank=None,
        )
    except Exception as exc:
        logger.debug(f"[TSP Intraday] match_symbol_tsp_mainline exception: {exc}")
        return TSPMainlineMatch(
            is_mainline=False,
            sector_name="",
            score=0.0,
            highest_board=1,
            rank=None,
        )


def is_symbol_in_top_n_mainlines(
    code: str,
    symbol_data: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    top_n: int = 3,
    *,
    live_breadth: Optional[dict[str, Any]] = None,
) -> bool:
    """Check if symbol belongs to any of the top N mainline sectors."""
    match = match_symbol_tsp_mainline(
        code,
        symbol_data,
        settings,
        live_breadth=live_breadth,
    )
    return bool(match.rank is not None and match.rank <= top_n)


def check_intraday_retreat_risk(
    settings: Optional[dict[str, Any]] = None,
    live_breadth: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Check if intraday retreat condition is triggered (e.g. broken_rate >= 35% and limit_down >= 10).

    Returns (is_retreat, reasoning).
    """
    cfg = tsp_quant_cfg(settings)
    intraday_cfg = cfg.get("intraday") or {}
    if not cfg.get("enabled", True) or not intraday_cfg.get("enabled", True):
        return False, ""

    threshold = float(intraday_cfg.get("intraday_retreat_broken_rate", 0.35))
    breadth = live_breadth or get_live_market_breadth_and_phase(settings)

    broken_rate = float(breadth.get("broken_rate") or 0.0)
    limit_down = int(breadth.get("limit_down") or breadth.get("limit_down_count") or 0)

    if broken_rate >= threshold and limit_down >= 10:
        return (
            True,
            f"TSP 盘中退潮急刹车：炸板率 {broken_rate * 100:.1f}% ≥ {threshold * 100:.0f}% 且跌停 {limit_down} 家 ≥ 10 家，禁止追高买入",
        )

    return False, ""


def format_tsp_intraday_card_markdown(
    symbol_code: str,
    symbol_data: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    *,
    live_breadth: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Generate Markdown status lines for TSP intraday scan/trade cards.

    Includes:
    - 盘中情绪周期与炸板率
    - 标的主线题材归属与得分
    - 交易所偏离度动态安全垫或异动预警
    """
    cfg = tsp_quant_cfg(settings)
    intraday_cfg = cfg.get("intraday") or {}
    if not cfg.get("enabled", True):
        return []

    lines: list[str] = []
    card_enabled = intraday_cfg.get("card_display_enabled", True) is not False
    deviation_enabled = cfg.get("deviation_enabled", True) is not False

    # 1. Deviation Sentinel
    risk: dict[str, Any] = {}
    if deviation_enabled:
        try:
            from agent_reach.daily_run.tsp.deviation_monitor import compute_exchange_deviation_risk

            risk = compute_exchange_deviation_risk(
                symbol_data if isinstance(symbol_data, dict) else {},
                warning_ratio=float(cfg.get("deviation_warning_ratio", 0.85)),
                block_ratio=float(cfg.get("deviation_block_buy_ratio", 0.90)),
            )
        except Exception:
            risk = {}

    if not card_enabled:
        if risk.get("warning"):
            icon = "🛑" if risk.get("blocked_buy") else "⚠️"
            lines.append(f"**{icon} 交易所偏离监管：** {risk.get('reason')}")
        return lines

    # Full TSP status strip
    strip_items: list[str] = []

    # A. Intraday sentiment phase & broken rate
    breadth = live_breadth or get_live_market_breadth_and_phase(settings)
    phase_name = breadth.get("phase_name") or "未知"
    broken_pct = float(breadth.get("broken_rate") or 0.0) * 100.0
    strip_items.append(f"盘中情绪：{phase_name} · 炸板率 {broken_pct:.1f}%")

    # B. Mainline match & strength score
    if symbol_code:
        match = match_symbol_tsp_mainline(
            symbol_code,
            symbol_data,
            settings,
            live_breadth=breadth,
        )
        if match.sector_name:
            strip_items.append(
                f"主线归属：【{match.sector_name}】强度 {match.score:.1f}分 · 身位板 {match.highest_board}板"
            )
        else:
            strip_items.append("主线归属：轮动/非核心主线题材")

    # C. Deviation cushion or warning
    if risk.get("warning"):
        icon = "🛑" if risk.get("blocked_buy") else "⚠️"
        strip_items.append(f"{icon} 偏离监管预警：{risk.get('reason')}")
    else:
        dist = float(risk.get("distance_to_limit_pct") or 0.0)
        limit_3d = float(risk.get("limit_3d") or 20.0)
        strip_items.append(f"异动安全垫：+{dist:.1f}%（距交易所 3日 {limit_3d:.0f}% 监管红线尚有空间）")

    if strip_items:
        try:
            from agent_reach.daily_run.panel.config import panel_card_link_enabled, panel_url

            if panel_card_link_enabled(settings):
                p_url = panel_url(settings)
                strip_items.append(f"🖥️ 实时大屏：[{p_url}]({p_url})")
        except Exception:
            pass

        lines.append("**TSP 量化哨兵：**")
        for item in strip_items:
            lines.append(f"- {item}")

    return lines

