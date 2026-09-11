# -*- coding: utf-8
"""Post-sell cooldown — block repeat sells/buys on a symbol (Freqtrade CooldownPeriod-style)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.protections.iprotection import ProtectionReturn, protections_cfg
from agent_reach.daily_run.snapshot_builder import _normalize_code

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _post_sell_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = protections_cfg(settings)
    block = dict(root.get("post_sell_cooldown") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "min_scans_after_sell": max(0, int(block.get("min_scans_after_sell", 2))),
        "block_before_hour": int(block.get("block_before_hour", 14)),
        "block_buy": block.get("block_buy", True) is not False,
        "block_sell": block.get("block_sell", True) is not False,
    }


def _last_applied_sell(
    prior_trades: Optional[list[dict[str, Any]]],
    code: str,
) -> Optional[dict[str, Any]]:
    norm = _normalize_code(code)
    for row in reversed(prior_trades or []):
        if not isinstance(row, dict):
            continue
        if _normalize_code(str(row.get("code") or "")) != norm:
            continue
        if str(row.get("action") or "").lower() != "sell":
            continue
        if row.get("portfolio_applied") is False:
            continue
        return row
    return None


def _scans_since_trade(
    trade: dict[str, Any],
    *,
    session_scans: Optional[list[dict[str, Any]]],
    prior_trades: Optional[list[dict[str, Any]]],
    code: str,
) -> int:
    trade_id = str(trade.get("trade_id") or "")
    norm = _normalize_code(code)
    seen_sell = False
    count = 0
    for row in prior_trades or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("trade_id") or "") == trade_id:
            seen_sell = True
            continue
        if seen_sell and _normalize_code(str(row.get("code") or "")) == norm:
            count += 1
    return count


def evaluate_post_sell_cooldown(
    *,
    code: str,
    name: str,
    side: str,
    settings: Optional[dict[str, Any]] = None,
    prior_trades: Optional[list[dict[str, Any]]] = None,
    session_scans: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Optional[ProtectionReturn]:
    cfg = _post_sell_cfg(settings)
    if not cfg["enabled"]:
        return None

    side_l = str(side or "").lower()
    if side_l == "buy" and not cfg["block_buy"]:
        return None
    if side_l == "sell" and not cfg["block_sell"]:
        return None
    if side_l not in {"buy", "sell"}:
        return None

    last_sell = _last_applied_sell(prior_trades, code)
    if last_sell is None:
        return None

    dt = now or datetime.now(_SH_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_SH_TZ)
    else:
        dt = dt.astimezone(_SH_TZ)

    min_scans = int(cfg["min_scans_after_sell"])
    scans_since = _scans_since_trade(
        last_sell,
        session_scans=session_scans,
        prior_trades=prior_trades,
        code=code,
    )
    before_hour = int(cfg["block_before_hour"])
    hour_block = side_l == "sell" and dt.hour < before_hour

    if scans_since >= min_scans and not hour_block:
        return None

    parts: list[str] = []
    if scans_since < min_scans:
        parts.append(f"卖后仅 {scans_since}/{min_scans} 次 scan")
    if hour_block:
        parts.append(f"{before_hour}:00 前暂缓同票卖出")
    reason = f"post_sell_cooldown：{' · '.join(parts)}"
    return ProtectionReturn(
        lock=True,
        until=None,
        reason=reason,
        lock_side=side_l,
        scope="pair",
        code=_normalize_code(code),
        name=name,
        protection="post_sell_cooldown",
    )
