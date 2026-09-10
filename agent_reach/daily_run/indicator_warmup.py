# -*- coding: utf-8
"""Indicator warmup guard (Backtrader prenext/min_period style)."""

from __future__ import annotations

from typing import Any, Optional


def indicator_warmup_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("indicator_warmup") or {})


def indicator_warmup_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return indicator_warmup_cfg(settings).get("enabled", True) is not False


def _mss_history_len(snapshot: dict[str, Any]) -> int:
    hist = snapshot.get("mss_history") or snapshot.get("mss_trajectory") or []
    if isinstance(hist, list):
        return len(hist)
    if isinstance(hist, dict):
        return len(hist)
    return 0


def indicator_warmup_block_reason(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    cfg = indicator_warmup_cfg(settings)
    if not indicator_warmup_enabled(settings):
        return None
    if cfg.get("block_auto_adjust", True) is False:
        return None
    min_points = max(1, int(cfg.get("min_mss_history_points", 2)))
    count = _mss_history_len(snapshot)
    if count <= 0:
        return None
    if count >= min_points:
        return None
    kronos = snapshot.get("kronos") or {}
    if cfg.get("require_kronos_when_enabled", False) and not kronos.get("available"):
        return "Kronos 未就绪，指标预热期禁止调仓"
    return f"指标预热期（MSS 样本 {count}/{min_points}），禁止自动调仓"
