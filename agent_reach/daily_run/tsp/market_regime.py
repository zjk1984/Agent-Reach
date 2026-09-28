# -*- coding: utf-8 -*-
"""TSP Market Phase & Sentiment Regime Classifier.

Implements the 6-phase sentiment cycle adapted from tick-stock-panel:
- freezing (冰点期): low limit-up count, high broken rate, low ladder height (< 3)
- launching (启动期): limit-ups start expanding, low broken rate, 2-board ladder emerging
- main_up (主升期): stable high ladder (>= 4), high晋级率, active mainline leadership
- climax (高潮期): high limit-up count (>= 50), extreme ladder height (>= 6), crowded
- retreat (退潮期): high-board stocks collapsing, high broken rate (>= 30%), ladder shrinking
- repair (修复期): post-retreat stabilization, broken rate dropping, low-board rebound

Also provides mapping from TSP 6-phase to Agent-Reach session regime:
- freezing / retreat -> defensive
- launching / main_up -> supportive
- climax / repair -> neutral (with tactical notes)
"""

from __future__ import annotations

from typing import Any, Optional


TSP_PHASE_NAMES: dict[str, str] = {
    "freezing": "冰点期 ❄️",
    "launching": "启动期 🚀",
    "main_up": "主升期 🔥",
    "climax": "高潮期 🌋",
    "retreat": "退潮期 🌊",
    "repair": "修复期 🛡️",
}


def _get_stock_board(stock: dict[str, Any]) -> int:
    """Helper to extract consecutive board number for a stock."""
    board = stock.get("consecutive_limit_ups")
    if board is None:
        pct = float(stock.get("change_pct") or 0.0)
        board = max(1, int(round(pct / 10))) if pct > 15 else 1
    try:
        return max(1, int(board))
    except (ValueError, TypeError):
        return 1


def compute_ladder_promotion_rates(
    limit_up_stocks: list[dict[str, Any]],
    yesterday_limit_up_stocks: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Calculate ladder progression and promotion rates between consecutive boards.

    Returns:
    {
        "count_1": int,
        "count_2": int,
        "count_3": int,
        "count_4_plus": int,
        "highest_board": int,
        "rate_1_to_2": float,
        "rate_2_to_3": float,
        "rate_high_promotion": float,
        "fault_status": "healthy" | "divergence" | "cliff",
        "fault_label": str,
        "summary": str,
    }
    """
    count_1 = 0
    count_2 = 0
    count_3 = 0
    count_4_plus = 0
    highest_board = 1

    for s in limit_up_stocks:
        b = _get_stock_board(s)
        highest_board = max(highest_board, b)
        if b == 1:
            count_1 += 1
        elif b == 2:
            count_2 += 1
        elif b == 3:
            count_3 += 1
        else:
            count_4_plus += 1

    if yesterday_limit_up_stocks is not None and len(yesterday_limit_up_stocks) > 0:
        yest_1 = sum(1 for s in yesterday_limit_up_stocks if _get_stock_board(s) == 1)
        yest_2 = sum(1 for s in yesterday_limit_up_stocks if _get_stock_board(s) == 2)
        yest_3_plus = sum(1 for s in yesterday_limit_up_stocks if _get_stock_board(s) >= 3)

        rate_1_to_2 = (count_2 / yest_1) if yest_1 > 0 else (count_2 / max(1, count_1 + count_2))
        rate_2_to_3 = (count_3 / yest_2) if yest_2 > 0 else (count_3 / max(1, count_2 + count_3))
        rate_high = (count_4_plus / yest_3_plus) if yest_3_plus > 0 else (count_4_plus / max(1, count_3 + count_4_plus))
    else:
        rate_1_to_2 = count_2 / max(1, count_1 + count_2) if (count_1 + count_2) > 0 else 0.0
        rate_2_to_3 = count_3 / max(1, count_2 + count_3) if (count_2 + count_3) > 0 else 0.0
        rate_high = count_4_plus / max(1, count_3 + count_4_plus) if (count_3 + count_4_plus) > 0 else 0.0

    # Clamp to 0.0 .. 1.0
    rate_1_to_2 = max(0.0, min(1.0, float(rate_1_to_2)))
    rate_2_to_3 = max(0.0, min(1.0, float(rate_2_to_3)))
    rate_high = max(0.0, min(1.0, float(rate_high)))

    # Detect fault status
    if (count_2 >= 2 and rate_2_to_3 < 0.15) or (count_2 >= 3 and count_3 == 0):
        fault_status = "cliff"
        fault_label = "2进3严重断崖 ⚠️"
    elif rate_1_to_2 < 0.20 or rate_2_to_3 < 0.25:
        fault_status = "divergence"
        fault_label = "接力分歧 ⚡"
    else:
        fault_status = "healthy"
        fault_label = "梯队健康 🟢"

    summary = (
        f"连板天梯：1→2: {rate_1_to_2 * 100:.1f}% · 2→3: {rate_2_to_3 * 100:.1f}% "
        f"({fault_label}) · 最高 {highest_board} 板"
    )

    return {
        "count_1": count_1,
        "count_2": count_2,
        "count_3": count_3,
        "count_4_plus": count_4_plus,
        "highest_board": highest_board,
        "rate_1_to_2": round(rate_1_to_2, 3),
        "rate_2_to_3": round(rate_2_to_3, 3),
        "rate_high_promotion": round(rate_high, 3),
        "fault_status": fault_status,
        "fault_label": fault_label,
        "summary": summary,
    }


def compute_tsp_market_phase(
    *,
    limit_up_count: int = 0,
    limit_down_count: int = 0,
    broken_rate: float = 0.0,
    highest_board: int = 1,
    two_board_count: int = 0,
    yesterday_phase: Optional[str] = None,
    limit_up_stocks: Optional[list[dict[str, Any]]] = None,
    yesterday_limit_up_stocks: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Calculate market phase and indicators from limit-up breadth and ladder state."""
    phase = classify_tsp_market_phase(
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        broken_rate=broken_rate,
        highest_board=highest_board,
        two_board_count=two_board_count,
        yesterday_phase=yesterday_phase,
    )
    session_regime = map_tsp_phase_to_session_regime(phase)
    summary = format_tsp_regime_summary(
        phase=phase,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        broken_rate=broken_rate,
        highest_board=highest_board,
    )
    promotion_ladder = compute_ladder_promotion_rates(
        limit_up_stocks=limit_up_stocks or [],
        yesterday_limit_up_stocks=yesterday_limit_up_stocks,
    )

    return {
        "phase": phase,
        "phase_name": TSP_PHASE_NAMES.get(phase, phase),
        "session_regime": session_regime,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "broken_rate": round(broken_rate, 4),
        "highest_board": highest_board,
        "two_board_count": two_board_count,
        "promotion_ladder": promotion_ladder,
        "summary": summary,
    }


def classify_tsp_market_phase(
    *,
    limit_up_count: int,
    limit_down_count: int,
    broken_rate: float,
    highest_board: int,
    two_board_count: int,
    yesterday_phase: Optional[str] = None,
) -> str:
    """Classify 6-phase cycle using deterministic rules."""
    # 1. Climax: Massive limit-ups or ultra-high ladder with low broken rate
    if (limit_up_count >= 50 and broken_rate <= 0.25) or (highest_board >= 7 and limit_up_count >= 35):
        return "climax"

    # 2. Retreat: Falling from climax/main_up or high broken rate with heavy limit-downs
    if (
        broken_rate >= 0.35
        or limit_down_count >= 15
        or (yesterday_phase in ("climax", "main_up") and (highest_board < 4 or broken_rate >= 0.30))
    ):
        return "retreat"

    # 3. Freezing: Market is extremely quiet or deeply depressed (or 0 limit up)
    if limit_up_count <= 18 and highest_board <= 3:
        return "freezing"
    if limit_up_count == 0:
        return "freezing"

    # 4. Repair: Following a retreat/freezing, broken rate drops and floor stabilizes
    if yesterday_phase in ("retreat", "freezing") and broken_rate <= 0.28 and limit_up_count >= 20:
        return "repair"

    # 5. Main Up: Solid high board (>= 5, or >= 4 with strong breadth >= 35) and strong continuation
    if (highest_board >= 5 and limit_up_count >= 30 and broken_rate <= 0.25) or (
        highest_board >= 4 and limit_up_count >= 35 and broken_rate <= 0.22
    ):
        return "main_up"

    # 6. Launching: Ladder expansion starting from low boards (2-4 boards)
    if (two_board_count >= 3 or limit_up_count >= 20) and highest_board in (2, 3, 4) and broken_rate <= 0.25:
        return "launching"

    # Default fallback heuristics
    if limit_down_count > limit_up_count:
        return "retreat"
    if limit_up_count >= 30:
        return "main_up"
    if broken_rate >= 0.30:
        return "retreat"
    return "repair" if yesterday_phase == "retreat" else "launching"


def map_tsp_phase_to_session_regime(phase: str) -> str:
    """Map TSP market phase to Agent-Reach session regime ('defensive', 'supportive', 'neutral')."""
    if phase in ("freezing", "retreat"):
        return "defensive"
    if phase in ("launching", "main_up"):
        return "supportive"
    return "neutral"


def format_tsp_regime_summary(
    *,
    phase: str,
    limit_up_count: int,
    limit_down_count: int,
    broken_rate: float,
    highest_board: int,
) -> str:
    """Render a human-readable one-line summary of TSP market regime."""
    phase_label = TSP_PHASE_NAMES.get(phase, phase)
    broken_pct = broken_rate * 100.0
    return (
        f"TSP 情绪周期：{phase_label}（最高 {highest_board} 板 · 涨停 {limit_up_count} / "
        f"跌停 {limit_down_count} · 炸板率 {broken_pct:.1f}%）"
    )
