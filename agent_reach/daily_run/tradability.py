# -*- coding: utf-8
"""A-share per-symbol tradability gates: board price-limit %, limit-up/down, suspension.

Paper-trading heuristics, not exact real-order-matching rules — e.g. ST edge cases
around the 2020 registration-reform transition are approximated. The goal is only
to stop the paper ledger from recording buys/sells that would not realistically
fill (chasing a one-word limit-up, "selling" into a limit-down, or trading a
suspended symbol), which would otherwise distort paper P&L and harness evolution.
"""

from __future__ import annotations

from typing import Any, Optional

# Daily price-limit % (up/down) tolerance around the exact limit, to absorb
# rounding noise in change_pct (ticks vs. percentage rounding).
_LIMIT_EPSILON_PCT = 0.15


def board_limit_pct(code: str, name: Optional[str] = None) -> float:
    """Daily price-limit % (up/down) for the board a symbol trades on."""
    text = str(code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.zfill(6)

    if text.startswith("688"):  # STAR Market (科创板)
        return 20.0
    if text.startswith(("300", "301")):  # ChiNext (创业板)
        return 20.0
    if text.startswith(("4", "8", "92")):  # Beijing Stock Exchange (北交所)
        return 30.0

    is_st = "ST" in str(name or "").upper()
    return 5.0 if is_st else 10.0  # Main board (SH 60x / SZ 00x); ST halves to 5%


def price_limit_state(change_pct: Optional[float], limit_pct: float) -> Optional[str]:
    """Classify change_pct against the board limit: "limit_up" / "limit_down" / None."""
    if change_pct is None:
        return None
    try:
        change_pct = float(change_pct)
    except (TypeError, ValueError):
        return None
    if change_pct >= limit_pct - _LIMIT_EPSILON_PCT:
        return "limit_up"
    if change_pct <= -limit_pct + _LIMIT_EPSILON_PCT:
        return "limit_down"
    return None


def is_suspended(row: dict[str, Any]) -> bool:
    """Heuristic: zero traded volume/amount on an otherwise-quoted symbol.

    Fails open (returns False) when no volume/amount field is available from
    the active quote source — most sources here don't carry it, so this is a
    best-effort signal rather than a guarantee.
    """
    for key in ("volume", "turnover"):
        value = row.get(key)
        if value is None:
            continue
        try:
            if float(value) == 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def tradability_block_reason(
    row: dict[str, Any],
    *,
    side: str,
    code: Optional[str] = None,
) -> Optional[str]:
    """Human-readable block reason if `side` ("buy"/"sell") isn't realistically
    fillable for this symbol right now (limit-up/down, suspension), else None.

    Fails open when change_pct / volume data isn't present on `row` — callers
    should not treat a None return as a guarantee of tradability, only as "no
    known reason to block".
    """
    resolved_code = str(code if code is not None else row.get("code") or "")
    name = str(row.get("name") or resolved_code)
    side_label = "买入" if side == "buy" else "卖出"

    if is_suspended(row):
        return f"{name}（{resolved_code}）当日成交量为 0，疑似停牌，跳过{side_label}"

    limit_pct = board_limit_pct(resolved_code, name)
    state = price_limit_state(row.get("change_pct"), limit_pct)
    if state == "limit_up" and side == "buy":
        change_pct = float(row["change_pct"])
        return f"{name}（{resolved_code}）涨停 {change_pct:+.2f}%（板块限制 ±{limit_pct:.0f}%），大概率无法买入成交，跳过"
    if state == "limit_down" and side == "sell":
        change_pct = float(row["change_pct"])
        return f"{name}（{resolved_code}）跌停 {change_pct:+.2f}%（板块限制 ±{limit_pct:.0f}%），大概率无法卖出成交，跳过"
    return None
