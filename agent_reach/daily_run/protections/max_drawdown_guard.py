# -*- coding: utf-8
"""Global stop after consecutive losing sells (Freqtrade MaxDrawdown-style)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.protections.iprotection import ProtectionReturn, protections_cfg


def _max_dd_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = protections_cfg(settings)
    block = dict(root.get("max_drawdown") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "max_losing_streak": max(1, int(block.get("max_losing_streak", 3))),
        "lookback_trades": max(1, int(block.get("lookback_trades", 8))),
        "stop_duration_scans": max(1, int(block.get("stop_duration_scans", 3))),
        "block_buy": block.get("block_buy", True) is not False,
    }


def _recent_losing_sell_streak(prior_trades: Optional[list[dict[str, Any]]], lookback: int) -> int:
    streak = 0
    checked = 0
    for row in reversed(prior_trades or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("action") or "").lower() != "sell":
            continue
        if row.get("portfolio_applied") is False:
            continue
        checked += 1
        pnl = row.get("realized_pnl")
        if pnl is None:
            msg = str(row.get("portfolio_message") or row.get("reasoning") or "")
            if "盈亏" in msg and "-" in msg:
                streak += 1
            else:
                break
        elif float(pnl) < 0:
            streak += 1
        else:
            break
        if checked >= lookback:
            break
    return streak


def _global_stop_active(
    prior_trades: Optional[list[dict[str, Any]]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> bool:
    cfg = _max_dd_cfg(settings)
    trades = [t for t in (prior_trades or []) if isinstance(t, dict)]
    if not trades:
        return False

    streak = 0
    trigger_idx: Optional[int] = None
    for idx in range(len(trades) - 1, -1, -1):
        row = trades[idx]
        if str(row.get("action") or "").lower() != "sell":
            continue
        if row.get("portfolio_applied") is False:
            continue
        pnl = row.get("realized_pnl")
        losing = False
        if pnl is not None:
            losing = float(pnl) < 0
        else:
            msg = str(row.get("portfolio_message") or row.get("reasoning") or "")
            losing = "盈亏" in msg and "-" in msg
        if losing:
            streak += 1
            if streak >= cfg["max_losing_streak"]:
                trigger_idx = idx
                break
        else:
            break

    if trigger_idx is None:
        return False

    scans_after = len(trades) - trigger_idx - 1
    return scans_after < cfg["stop_duration_scans"]


def evaluate_max_drawdown_guard(
    *,
    side: str,
    settings: Optional[dict[str, Any]] = None,
    prior_trades: Optional[list[dict[str, Any]]] = None,
) -> Optional[ProtectionReturn]:
    cfg = _max_dd_cfg(settings)
    if not cfg["enabled"]:
        return None
    if str(side or "").lower() != "buy" or not cfg["block_buy"]:
        return None
    if not _global_stop_active(prior_trades, settings=settings):
        return None
    streak = _recent_losing_sell_streak(prior_trades, cfg["lookback_trades"])
    return ProtectionReturn(
        lock=True,
        until=None,
        reason=(
            f"max_drawdown_guard：连续 {streak} 笔亏损卖出，"
            f"全局暂停买入 {cfg['stop_duration_scans']} scan"
        ),
        lock_side="buy",
        scope="global",
        protection="max_drawdown_guard",
    )
