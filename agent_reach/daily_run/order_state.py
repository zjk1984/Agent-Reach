# -*- coding: utf-8
"""Lightweight order state machine (Backtrader Order.* inspired)."""

from __future__ import annotations

from typing import Any, Optional

ORDER_COMPLETE = "complete"
ORDER_REJECTED = "rejected"
ORDER_MARGIN = "margin"
ORDER_CANCELLED = "cancelled"


def order_state_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("order_state") or {})


def order_state_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return order_state_cfg(settings).get("enabled", True) is not False


def classify_reject_reason(message: str) -> str:
    text = str(message or "").strip().lower()
    if not text:
        return "unknown"
    if "现金" in text or "cash" in text or "不足" in text:
        return ORDER_MARGIN
    if "t+1" in text or "锁仓" in text:
        return ORDER_REJECTED
    if "阻断" in text or "blocked" in text or "摩擦" in text:
        return ORDER_REJECTED
    if "涨跌停" in text or "tradability" in text:
        return ORDER_REJECTED
    return ORDER_REJECTED


def order_state_for_apply(*, applied: bool, message: str = "") -> str:
    if applied:
        return ORDER_COMPLETE
    reason = classify_reject_reason(message)
    return reason if reason != "unknown" else ORDER_REJECTED


def enrich_trade_metadata(
    payload: dict[str, Any],
    *,
    applied: bool,
    message: str = "",
    settings: Optional[dict[str, Any]] = None,
    execution_meta: Optional[dict[str, Any]] = None,
    oco_group_id: Optional[str] = None,
) -> dict[str, Any]:
    if not order_state_enabled(settings):
        return payload
    out = dict(payload)
    out["order_state"] = order_state_for_apply(applied=applied, message=message)
    if not applied and message:
        out["reject_reason"] = str(message)[:160]
    if execution_meta:
        if execution_meta.get("fill_timing"):
            out["fill_timing"] = execution_meta["fill_timing"]
        if execution_meta.get("slippage_rate") is not None:
            out["slippage_rate"] = execution_meta["slippage_rate"]
        if execution_meta.get("volume_limited"):
            out["volume_limited"] = True
    if oco_group_id:
        out["oco_group_id"] = oco_group_id
    return out
