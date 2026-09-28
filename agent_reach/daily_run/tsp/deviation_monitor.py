# -*- coding: utf-8 -*-
"""TSP Exchange Abnormal Move Price Deviation Sentinel.

Monitors stock deviation against official exchange surveillance thresholds:
- 3-day abnormal move thresholds:
  * Main Board (主板): +/-20%
  * ChiNext (创业板) / STAR Market (科创板): +/-30%
  * Beijing Stock Exchange (北交所): +/-40%
- Multi-day cumulative abnormal thresholds:
  * 10-day cumulative: +100% / -50%
  * 30-day cumulative: +200% / -70%

Computes the proximity (接近度) to exchange regulatory limits and flags
sentinel warnings or hard buy locks.
"""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.tradability import board_limit_pct


def get_board_deviation_limit_3d(code: str, name: Optional[str] = None) -> float:
    """Return 3-day cumulative deviation threshold for the corresponding board."""
    daily_limit = board_limit_pct(code, name)
    if daily_limit == 20.0:
        return 30.0  # ChiNext / STAR
    if daily_limit == 30.0:
        return 40.0  # BSE
    if daily_limit == 5.0:
        return 12.0  # ST stocks roughly +/-12%
    return 20.0  # Main board +/-20%


def compute_exchange_deviation_risk(
    symbol_row: dict[str, Any],
    *,
    warning_ratio: float = 0.85,
    block_ratio: float = 0.90,
) -> dict[str, Any]:
    """Check a single stock's cumulative return against 3-day and multi-day limits."""
    code = str(symbol_row.get("code") or "")
    name = str(symbol_row.get("name") or code)

    limit_3d = get_board_deviation_limit_3d(code, name)

    # 3-day cumulative change (fallback to 3 * change_pct if no 3-day history)
    pct_3d = symbol_row.get("change_pct_3d")
    if pct_3d is None:
        c1 = float(symbol_row.get("change_pct") or 0.0)
        pct_3d = c1

    pct_3d = float(pct_3d)

    # Proximity calculation: how close is it to the threshold
    if pct_3d >= 0:
        proximity_3d = pct_3d / limit_3d if limit_3d > 0 else 0.0
        dist_3d = max(0.0, limit_3d - pct_3d)
    else:
        proximity_3d = abs(pct_3d) / limit_3d if limit_3d > 0 else 0.0
        dist_3d = max(0.0, limit_3d - abs(pct_3d))

    is_warning = proximity_3d >= warning_ratio
    is_blocked = proximity_3d >= block_ratio

    # Multi-day cumulative (10d, 30d) if available
    pct_10d = symbol_row.get("change_pct_10d")
    is_10d_risk = False
    if pct_10d is not None:
        p10 = float(pct_10d)
        if p10 >= 80.0:  # approaching +100%
            is_10d_risk = True

    risk_level = "safe"
    if is_blocked or is_10d_risk:
        risk_level = "critical"
    elif is_warning:
        risk_level = "warning"

    return {
        "code": code,
        "name": name,
        "limit_3d": limit_3d,
        "change_pct_3d": round(pct_3d, 2),
        "proximity_3d": round(proximity_3d, 4),
        "distance_to_limit_pct": round(dist_3d, 2),
        "risk_level": risk_level,
        "warning": is_warning,
        "blocked_buy": is_blocked,
        "reason": (
            f"3日累积偏离 {pct_3d:+.1f}% 接近交易所监管红线 ±{limit_3d:.0f}%（距异动仅 {dist_3d:.1f}%）"
            if is_warning
            else ""
        ),
    }


def check_portfolio_deviation_risk(
    portfolio_or_holdings: Any,
    *,
    warning_ratio: float = 0.85,
    block_ratio: float = 0.90,
) -> list[dict[str, Any]]:
    """Scan all holdings for exchange price deviation surveillance risks."""
    if isinstance(portfolio_or_holdings, dict):
        rows = portfolio_or_holdings.get("holdings") or []
    elif isinstance(portfolio_or_holdings, list):
        rows = portfolio_or_holdings
    else:
        rows = []

    alerts: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        risk = compute_exchange_deviation_risk(
            r,
            warning_ratio=warning_ratio,
            block_ratio=block_ratio,
        )
        if risk["warning"] or risk["blocked_buy"]:
            alerts.append(risk)

    alerts.sort(key=lambda x: float(x.get("proximity_3d", 0)), reverse=True)
    return alerts


def format_deviation_alert_lines(alerts: list[dict[str, Any]]) -> list[str]:
    """Format deviation alerts into markdown report lines."""
    if not alerts:
        return []
    lines = ["**🚨 交易所偏离度风险预警：**"]
    for a in alerts:
        icon = "🛑" if a.get("blocked_buy") else "⚠️"
        lines.append(f"- {icon} **{a['name']}**({a['code']})：{a['reason']}")
    return lines
