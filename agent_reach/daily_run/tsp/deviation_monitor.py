# -*- coding: utf-8 -*-
"""TSP Exchange Abnormal Move Price Deviation Sentinel.

Monitors stock deviation against official exchange surveillance thresholds:
- 3-day abnormal move thresholds:
  * Main Board (主板): +/-20%
  * ChiNext (创业板) / STAR Market (科创板): +/-30%
  * Beijing Stock Exchange (北交所 920/43/8x): +/-40%
  * ST / *ST stocks: +/-12%
- Multi-day cumulative abnormal thresholds:
  * 10-day cumulative: +100% / -50%
  * 30-day cumulative: +200% / -70%

Computes the proximity (接近度) to exchange regulatory limits and flags
sentinel warnings or hard buy locks.
"""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.tradability import board_limit_pct


def _parse_pct_float(val: Any) -> Optional[float]:
    """Safely parse percentage numeric strings or floats (e.g. '+9.98%', '5.2', None)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    if text.startswith("+"):
        text = text[1:].strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def get_board_deviation_limit_3d(code: str, name: Optional[str] = None) -> float:
    """Return 3-day cumulative deviation threshold for the corresponding board."""
    norm_code = str(code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if norm_code.startswith(prefix):
            norm_code = norm_code[len(prefix):]
            break
    norm_code = norm_code.zfill(6)

    # BSE (北交所) 920xxx, 43xxxx, 8xxxxx
    if norm_code.startswith(("920", "43", "8")):
        return 40.0

    daily_limit = board_limit_pct(norm_code, name)
    if daily_limit == 20.0:
        return 30.0  # ChiNext / STAR
    if daily_limit == 30.0:
        return 40.0  # BSE
    if daily_limit == 5.0 or "ST" in str(name or "").upper():
        return 12.0  # ST stocks +/-12%
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

    # 3-day cumulative change (fallback to 1-day change or quote nested if missing)
    pct_3d = _parse_pct_float(symbol_row.get("change_pct_3d"))
    if pct_3d is None:
        c1 = _parse_pct_float(symbol_row.get("change_pct"))
        if c1 is None:
            # Try nested quote or snapshot fields
            quote = symbol_row.get("quote") if isinstance(symbol_row.get("quote"), dict) else {}
            c1 = _parse_pct_float(quote.get("change_pct"))
        if c1 is None:
            # Try calculating from price / reference_price
            p = _parse_pct_float(symbol_row.get("price"))
            ref = _parse_pct_float(symbol_row.get("reference_price") or symbol_row.get("pre_close"))
            if p is not None and ref is not None and ref > 0:
                c1 = round((p - ref) / ref * 100.0, 2)
        pct_3d = c1 if c1 is not None else 0.0

    pct_3d = float(pct_3d)

    # Proximity calculation: how close is it to the threshold
    if pct_3d >= 0:
        proximity_3d = pct_3d / limit_3d if limit_3d > 0 else 0.0
        dist_3d = max(0.0, limit_3d - pct_3d)
        is_downside = False
    else:
        proximity_3d = abs(pct_3d) / limit_3d if limit_3d > 0 else 0.0
        dist_3d = max(0.0, limit_3d - abs(pct_3d))
        is_downside = True

    is_warning = proximity_3d >= warning_ratio
    # Only block buy orders when approaching UPPER limit (chasing overbought),
    # severe downside triggers warning but not "prohibit chasing buy"
    is_blocked = (proximity_3d >= block_ratio) and (not is_downside)

    # Multi-day cumulative (10d, 30d) if available
    pct_10d = _parse_pct_float(symbol_row.get("change_pct_10d"))
    is_10d_risk = False
    if pct_10d is not None and pct_10d >= 80.0:  # approaching +100%
        is_10d_risk = True

    risk_level = "safe"
    if is_blocked or is_10d_risk:
        risk_level = "critical"
    elif is_warning:
        risk_level = "warning"

    if is_warning:
        if is_downside:
            reason = (
                f"3日累积下跌偏离 {pct_3d:+.1f}% 接近交易所下向异动红线 -{limit_3d:.0f}%（距异动仅 {dist_3d:.1f}%）"
            )
        else:
            reason = (
                f"3日累积偏离 {pct_3d:+.1f}% 接近交易所监管红线 +{limit_3d:.0f}%（距异动仅 {dist_3d:.1f}%）"
            )
    else:
        reason = ""

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
        "is_downside": is_downside,
        "reason": reason,
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
