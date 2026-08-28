# -*- coding: utf-8 -*-
"""Intraday profit-lock (dynamic take-profit) for holdings at intraday highs."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_PROFIT_LOCK_STATIC_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "trigger_mode": "threshold",
    "once_per_symbol_per_day": True,
}


def profit_lock_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _profit_lock_policy

    return _profit_lock_policy(settings or {})


def profit_lock_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.harness_policy import profit_lock_policy_default

    cfg_settings = settings or {}
    intraday = dict(cfg_settings.get("intraday") or {})
    block = dict(intraday.get("profit_lock") or {})
    out: dict[str, Any] = {
        **_PROFIT_LOCK_STATIC_DEFAULTS,
        **block,
        "min_intraday_gain_pct": profit_lock_policy_default(cfg_settings, "min_intraday_gain_pct"),
        "min_position_20d": profit_lock_policy_default(cfg_settings, "min_position_20d"),
        "min_unrealized_gain_pct": profit_lock_policy_default(
            cfg_settings, "min_unrealized_gain_pct"
        ),
        "sell_ratio": profit_lock_policy_default(cfg_settings, "sell_ratio"),
        "pullback_from_high_pct": profit_lock_policy_default(
            cfg_settings, "pullback_from_high_pct"
        ),
    }
    out["enabled"] = block.get("enabled", out.get("enabled", True))
    return out


def _holding_for_code(snapshot: dict[str, Any], code: Any) -> Optional[dict[str, Any]]:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return None
    pf = snapshot.get("portfolio") or {}
    for holding in pf.get("holdings") or []:
        if _normalize_code(str(holding.get("code", ""))) == norm:
            return holding
    return None


def _symbol_field(
    snapshot: dict[str, Any],
    code: Any,
    key: str,
    *,
    holding: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    holding = holding or _holding_for_code(snapshot, code)
    if holding and holding.get(key) is not None:
        try:
            return float(holding[key])
        except (TypeError, ValueError):
            pass
    norm = _normalize_code(str(code or ""))
    if norm and _normalize_code(str(snapshot.get("code") or "")) == norm:
        val = snapshot.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    for row in snapshot.get("symbols") or []:
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        val = row.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _unrealized_gain_pct(holding: dict[str, Any], price: Optional[float]) -> Optional[float]:
    cost = holding.get("cost")
    if cost is None or price is None:
        return None
    try:
        cost_f = float(cost)
        price_f = float(price)
    except (TypeError, ValueError):
        return None
    if cost_f <= 0:
        return None
    return (price_f - cost_f) / cost_f * 100.0


def _session_high_price(
    session_scans: Optional[list[dict[str, Any]]],
    code: Any,
    *,
    current_price: Optional[float] = None,
) -> Optional[float]:
    norm = _normalize_code(str(code or ""))
    prices: list[float] = []
    if current_price is not None:
        prices.append(float(current_price))
    for scan in session_scans or []:
        if norm and _normalize_code(str(scan.get("code") or "")) not in ("", norm):
            continue
        price = scan.get("price")
        if price is None:
            continue
        try:
            prices.append(float(price))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    return max(prices)


def profit_lock_already_applied(
    prior_trades: Optional[list[dict[str, Any]]],
    code: Any,
) -> bool:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return False
    for trade in prior_trades or []:
        if str(trade.get("action") or "") != "sell":
            continue
        if not trade.get("portfolio_applied"):
            continue
        if _normalize_code(str(trade.get("code") or "")) != norm:
            continue
        if trade.get("sell_kind") == "profit_lock" or "动态止盈" in str(trade.get("reasoning") or ""):
            return True
    return False


def evaluate_profit_lock_sell(
    settings: dict[str, Any],
    *,
    report: dict[str, Any],
    snapshot: dict[str, Any],
    prior_trades: Optional[list[dict[str, Any]]] = None,
    session_scans: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, Optional[str], Optional[float]]:
    """Return (allow_sell, hold_reason, sell_ratio)."""
    cfg = profit_lock_cfg(settings)
    if not cfg.get("enabled", True):
        return False, None, None

    code = report.get("code")
    holding = _holding_for_code(snapshot, code)
    if holding is None:
        return False, None, None

    if cfg.get("once_per_symbol_per_day", True) and profit_lock_already_applied(prior_trades, code):
        return False, "今日已执行动态止盈减仓，同标的不再重复", None

    change_pct = _symbol_field(snapshot, code, "change_pct", holding=holding)
    position_20d = _symbol_field(snapshot, code, "position_20d", holding=holding)
    price = _symbol_field(snapshot, code, "price", holding=holding)
    min_gain = float(cfg.get("min_intraday_gain_pct", 4.0))
    min_pos = float(cfg.get("min_position_20d", 0.70))
    min_unrealized = float(cfg.get("min_unrealized_gain_pct", 3.0))

    if change_pct is None or change_pct < min_gain:
        return False, None, None
    if position_20d is None or position_20d < min_pos:
        return False, None, None

    unrealized_pct = _unrealized_gain_pct(holding, price)
    if unrealized_pct is not None and unrealized_pct < min_unrealized:
        return False, None, None

    trigger_mode = str(cfg.get("trigger_mode") or "threshold").strip().lower()
    if trigger_mode in ("pullback", "both"):
        session_high = _session_high_price(session_scans, code, current_price=price)
        pullback_pct = float(cfg.get("pullback_from_high_pct", 1.5))
        if session_high is None or price is None or session_high <= 0:
            return False, None, None
        drop_pct = (session_high - price) / session_high * 100.0
        if trigger_mode == "pullback":
            if drop_pct < pullback_pct:
                return False, None, None
        else:
            if drop_pct < pullback_pct and change_pct < min_gain + pullback_pct:
                return False, None, None

    sell_ratio = float(cfg.get("sell_ratio", 0.30))
    pos_part = f"20日位置 {position_20d:.0%}" if position_20d is not None else "20日位置偏高"
    unreal_part = f"，浮盈 {unrealized_pct:+.1f}%" if unrealized_pct is not None else ""
    reason = (
        f"标的今日 {change_pct:+.2f}% 且 {pos_part}{unreal_part}，"
        f"触发动态止盈（sell_ratio={sell_ratio:.0%}）"
    )
    return True, reason, sell_ratio


def profit_lock_effective_sell_ratio(
    settings: dict[str, Any],
    *,
    base_ratio: float,
    sell_ratio_override: Optional[float] = None,
) -> float:
    if sell_ratio_override is not None:
        return min(float(base_ratio), float(sell_ratio_override))
    return min(float(base_ratio), profit_lock_policy_default(settings, "sell_ratio"))
