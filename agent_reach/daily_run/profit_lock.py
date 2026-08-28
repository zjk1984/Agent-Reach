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


def profit_lock_harness_evidence(
    settings: dict[str, Any],
    *,
    code: str,
    name: str,
    scan_id: str,
    snapshot: dict[str, Any],
    decision: Optional[dict[str, Any]] = None,
    prior_trades: Optional[list[dict[str, Any]]] = None,
    session_scans: Optional[list[dict[str, Any]]] = None,
) -> dict[str, list[str]]:
    """Build harness memory/policy/playbook lines for profit-lock hits and misses."""
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    cfg = profit_lock_cfg(settings)
    if not cfg.get("enabled", True):
        return {"memory": memory, "policy": policy, "playbook": playbook}

    decision = dict(decision or {})
    action = str(decision.get("action") or "")
    sell_kind = decision.get("sell_kind")
    block_kind = str(decision.get("block_kind") or "")
    reasoning = str(decision.get("reasoning") or "")

    report = {"code": code, "name": name}
    allow, block_reason, ratio = evaluate_profit_lock_sell(
        settings,
        report=report,
        snapshot=snapshot,
        prior_trades=prior_trades,
        session_scans=session_scans,
    )

    if allow and action == "sell" and sell_kind == "profit_lock":
        playbook.append(
            f"动态止盈：{name}({code}) {scan_id} 高位减仓 sell_ratio={float(ratio or 0):.0%}"
        )
        return {"memory": memory, "policy": policy, "playbook": playbook}

    if allow and action != "sell":
        chg = _symbol_field(snapshot, code, "change_pct")
        chg_s = f"{float(chg):+.1f}%" if chg is not None else "高位"
        memory.append(
            f"卖晚了：{name}({code}) 盘中 {chg_s} 已触发动态止盈条件但决策为 {action or 'none'}"
        )
        policy.append(
            f"profit_lock：{name} 阈值已满足未 sell，下日 harness 收紧 min_intraday_gain_pct"
        )
        return {"memory": memory, "policy": policy, "playbook": playbook}

    if block_kind == "sell_profit_lock" and block_reason and "今日已执行" in block_reason:
        return {"memory": memory, "policy": policy, "playbook": playbook}

    holding = _holding_for_code(snapshot, code)
    change_pct = _symbol_field(snapshot, code, "change_pct", holding=holding)
    position_20d = _symbol_field(snapshot, code, "position_20d", holding=holding)
    price = _symbol_field(snapshot, code, "price", holding=holding)
    min_gain = float(cfg.get("min_intraday_gain_pct", 4.0))
    min_pos = float(cfg.get("min_position_20d", 0.70))

    if change_pct is None or change_pct < min_gain:
        return {"memory": memory, "policy": policy, "playbook": playbook}
    if position_20d is None or position_20d < min_pos:
        return {"memory": memory, "policy": policy, "playbook": playbook}

    if holding is None:
        playbook.append(
            f"观察池高位：{name}({code}) 盘中 {change_pct:+.1f}% 20日位置 {position_20d:.0%}，"
            f"持仓时应 profit_lock 锁利"
        )
        return {"memory": memory, "policy": policy, "playbook": playbook}

    if profit_lock_already_applied(prior_trades, code):
        return {"memory": memory, "policy": policy, "playbook": playbook}

    if action == "sell" and sell_kind == "profit_lock":
        return {"memory": memory, "policy": policy, "playbook": playbook}

    pullback_note = ""
    session_high = _session_high_price(session_scans, code, current_price=price)
    if session_high and price and session_high > float(price):
        drop_pct = (float(session_high) - float(price)) / float(session_high) * 100.0
        if drop_pct >= float(cfg.get("pullback_from_high_pct", 1.5)) * 0.5:
            pullback_note = f"，自日内高点 {session_high:.2f} 回落 {drop_pct:.1f}%"

    blocked_note = ""
    if "动态止盈信号触发，但" in reasoning:
        blocked_note = "（风控/锁仓阻断）"
    elif block_kind == "sell_deep_loss":
        blocked_note = "（深亏覆盖不足阻断）"

    memory.append(
        f"卖晚了：{name}({code}) 盘中 {change_pct:+.1f}% 20日位置 {position_20d:.0%}"
        f"{pullback_note} 未动态止盈{blocked_note}（{scan_id} decision={action or 'none'}）"
    )
    policy.append(
        "profit_lock：高位未及时减仓，下日 harness 收紧 min_intraday_gain_pct / 提高 sell_ratio"
    )
    return {"memory": memory, "policy": policy, "playbook": playbook}

