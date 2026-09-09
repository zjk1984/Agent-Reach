# -*- coding: utf-8
"""Watchlist momentum score boost for strong-day + actionable MSS verdicts."""

from __future__ import annotations

from typing import Any, Optional

_MOMENTUM_NEUTRAL: dict[str, Any] = {
    "enabled": True,
    "strong_day_pct": 2.0,
    "strong_verdict_boost": 1.5,
    "consecutive_strong_boost": 0.5,
}


def watchlist_momentum_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    wl = dict((settings or {}).get("watchlist") or {})
    block = dict(wl.get("momentum_score") or {})
    out = {**_MOMENTUM_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", True))
    return out


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _actionable_verdict(row: dict[str, Any], settings: Optional[dict[str, Any]]) -> bool:
    labels = dict((settings or {}).get("verdict_labels") or {})
    buy_label = str(labels.get("buy", "可做"))
    verdict = str(row.get("verdict") or row.get("verdict_current") or "")
    if verdict in {buy_label, "可做", "buy"}:
        return True
    mss = _optional_float(row.get("mss_final"))
    if mss is None:
        return False
    from agent_reach.daily_run.harness_policy import aggressive_entry_default

    return float(mss) >= aggressive_entry_default(settings or {})


def watchlist_momentum_score_boost(
    row: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> float:
    """Score boost when watchlist symbol is strong intraday with actionable MSS."""
    cfg = watchlist_momentum_cfg(settings)
    if not cfg.get("enabled", True):
        return 0.0

    chg = _optional_float(row.get("change_pct"))
    if chg is None or chg < float(cfg.get("strong_day_pct", 2.0)):
        return 0.0
    if not _actionable_verdict(row, settings):
        return 0.0

    boost = float(cfg.get("strong_verdict_boost", 1.5))
    streak = int(row.get("consecutive_strong_days") or row.get("strong_day_streak") or 0)
    if streak >= 2:
        boost += float(cfg.get("consecutive_strong_boost", 0.5))
    return boost
