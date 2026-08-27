# -*- coding: utf-8
"""Fast-path overlay when afternoon MSS rebounds but harness stays defensive."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from agent_reach.daily_run.intraday_scan_filters import scans_for_trend_detection


def _rebound_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    from agent_reach.daily_run.intraday_rebound_policy import rebound_effective_cfg

    return rebound_effective_cfg(settings)


def intraday_rebound_active(settings: dict[str, Any]) -> bool:
    runtime = settings.get("harness_runtime") or {}
    return bool((runtime.get("intraday_rebound") or {}).get("active"))


def detect_intraday_session_rebound(
    scans: list[dict[str, Any]],
    settings: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Detect afternoon-style MSS rebound from continuous session scans."""
    cfg = _rebound_cfg(settings)
    if cfg.get("enabled") is False:
        return None

    session_scans = scans_for_trend_detection(scans)
    min_session_scans = int(cfg.get("min_session_scans", 2))
    if len(session_scans) < min_session_scans:
        return None

    latest = session_scans[-1]
    latest_mss = float(latest.get("mss_final", 0))
    min_latest_mss = float(cfg.get("min_latest_mss", 50.0))
    if latest_mss < min_latest_mss:
        return None

    from agent_reach.daily_run.intraday_policy import detect_mss_trend

    trend = detect_mss_trend(session_scans, settings)
    allowed_trends = {str(x) for x in (cfg.get("trends") or ("rising", "turning_up"))}
    if trend not in allowed_trends:
        return None

    lookback = max(2, int(cfg.get("lookback_scans", 4)))
    window = session_scans[-lookback:]
    mss_values = [float(s.get("mss_final", 0)) for s in window]
    session_low = min(mss_values[:-1]) if len(mss_values) >= 2 else mss_values[0]
    min_mss_delta = float(cfg.get("min_mss_delta", 3.0))
    delta_from_low = latest_mss - session_low
    if delta_from_low < min_mss_delta:
        return None

    if cfg.get("require_defensive_trim", True):
        runtime = settings.get("harness_runtime") or {}
        trade_signals = runtime.get("trade_signals") or {}
        if not trade_signals.get("defensive_trim"):
            return None

    prev_mss = float(session_scans[-2].get("mss_final", 0))
    return {
        "active": True,
        "trend": trend,
        "latest_mss": round(latest_mss, 2),
        "session_low_mss": round(session_low, 2),
        "delta_from_low": round(delta_from_low, 2),
        "step_delta": round(latest_mss - prev_mss, 2),
        "latest_scan_id": latest.get("scan_id"),
    }


def apply_intraday_rebound_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
) -> dict[str, Any]:
    """Patch harness_runtime when a session rebound is detected."""
    rebound = detect_intraday_session_rebound(scans, settings)
    if not rebound:
        return settings

    cfg = deepcopy(settings)
    rebound_cfg = _rebound_cfg(settings)
    runtime = dict(cfg.get("harness_runtime") or {})

    runtime["intraday_rebound"] = rebound

    trade_signals = dict(runtime.get("trade_signals") or {})
    trade_signals["defensive_trim"] = False
    trade_signals["intraday_rebound"] = True
    runtime["trade_signals"] = trade_signals

    trend_policy = dict(runtime.get("trend_policy") or {})
    buy_trends = list(trend_policy.get("buy_trends") or ["rising", "turning_up"])
    for label in ("rising", "turning_up"):
        if label not in buy_trends:
            buy_trends.append(label)
    trend_policy["buy_trends"] = buy_trends
    rebound_delta = float(rebound_cfg.get("trend_delta_threshold", 0.8))
    trend_policy["trend_delta_threshold"] = min(
        float(trend_policy.get("trend_delta_threshold", 1.0)),
        rebound_delta,
    )
    runtime["trend_policy"] = trend_policy

    deep_loss = dict(runtime.get("deep_loss_policy") or {})
    deep_loss["sell_ratio"] = max(
        float(deep_loss.get("sell_ratio", 0.5)),
        float(rebound_cfg.get("deep_loss_sell_ratio", 0.75)),
    )
    deep_loss["non_deep_loss_sell_ratio"] = max(
        float(deep_loss.get("non_deep_loss_sell_ratio", 0.7)),
        float(rebound_cfg.get("non_deep_loss_sell_ratio", 0.85)),
    )
    runtime["deep_loss_policy"] = deep_loss

    def_trim = dict(runtime.get("defensive_trim_policy") or {})
    def_trim["defensive_trim_min_mss"] = min(
        float(def_trim.get("defensive_trim_min_mss", 42.0)),
        float(rebound_cfg.get("defensive_trim_min_mss", 40.0)),
    )
    def_trim["defensive_trim_mss_buffer"] = min(
        float(def_trim.get("defensive_trim_mss_buffer", 2.0)),
        float(rebound_cfg.get("defensive_trim_mss_buffer", 0.0)),
    )
    runtime["defensive_trim_policy"] = def_trim

    thresholds = dict(cfg.get("thresholds") or {})
    thresholds["aggressive_entry"] = max(
        float(thresholds.get("aggressive_entry", 45.0)),
        float(rebound_cfg.get("aggressive_entry", 48.0)),
    )
    thresholds["macro_veto"] = max(
        float(thresholds.get("macro_veto", 30.0)),
        float(rebound_cfg.get("macro_veto", 38.0)),
    )
    cfg["thresholds"] = thresholds

    cfg["harness_runtime"] = runtime
    return cfg
