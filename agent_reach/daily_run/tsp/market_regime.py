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


def compute_tsp_market_phase(
    *,
    limit_up_count: int = 0,
    limit_down_count: int = 0,
    broken_rate: float = 0.0,
    highest_board: int = 1,
    two_board_count: int = 0,
    yesterday_phase: Optional[str] = None,
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

    return {
        "phase": phase,
        "phase_name": TSP_PHASE_NAMES.get(phase, phase),
        "session_regime": session_regime,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "broken_rate": round(broken_rate, 4),
        "highest_board": highest_board,
        "two_board_count": two_board_count,
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

    # 3. Freezing: Market is extremely quiet or deeply depressed
    if limit_up_count <= 18 and highest_board <= 3:
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
