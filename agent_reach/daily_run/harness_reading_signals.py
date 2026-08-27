# -*- coding: utf-8
"""Live intraday MSS readings blended with harness memory trade signals."""

from __future__ import annotations

from typing import Any, Optional

_READING_NEUTRAL: dict[str, float] = {
    "recovery_min_mss": 52.0,
    "recovery_min_lookback": 52.0,
    "recovery_min_delta": 5.0,
    "recovery_macro_veto": 38.0,
    "recovery_aggressive_entry": 48.0,
}


def reading_signals_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.harness_reading_policy import (
        _EVOLVED_READING_KEYS,
        reading_effective_cfg,
        reading_mode,
    )

    harness = dict((settings or {}).get("harness") or {})
    block = dict(harness.get("reading_signals") or {})
    out = {**_READING_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", True)
    out["suppress_defensive_on_recovery"] = block.get("suppress_defensive_on_recovery", True)
    out["persist_macro_warming_on_close"] = block.get("persist_macro_warming_on_close", True)
    trends = block.get("recovery_trends")
    if isinstance(trends, list) and trends:
        out["recovery_trends"] = [str(x) for x in trends]
    else:
        out["recovery_trends"] = ["rising", "turning_up"]
    if reading_mode(settings) == "harness":
        evolved = reading_effective_cfg(settings)
        for key in _EVOLVED_READING_KEYS:
            out[key] = float(evolved.get(key, out[key]))
    return out


def _lookback_mss_from_scans(
    scans: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> float:
    """Lightweight lookback MSS without calling effective_settings (avoids overlay recursion)."""
    if not scans:
        return 0.0
    from agent_reach.daily_run.harness_policy import lookback_weights_default

    weights = lookback_weights_default(settings or {})
    recent = list(reversed(scans[-3:]))
    used = weights[: len(recent)]
    total_w = sum(used)
    if total_w <= 0:
        return float(recent[0].get("mss_final", 0))
    norm = [w / total_w for w in used]
    return round(
        sum(float(scan.get("mss_final", 0)) * w for scan, w in zip(recent, norm)),
        2,
    )


def _trend_from_scans(
    scans: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> str:
    intraday = dict((settings or {}).get("intraday") or {})
    min_pts = int(intraday.get("trend_min_points", 2))
    delta_thr = float(intraday.get("trend_delta_threshold", 1.0))
    if len(scans) < min_pts:
        return "insufficient"
    values = [float(s.get("mss_final", 0)) for s in scans[-3:]]
    if len(values) >= 3:
        d1 = values[-1] - values[-2]
        d2 = values[-2] - values[-3]
        if d1 > delta_thr and d2 > 0:
            return "turning_up"
        if d1 < -delta_thr and d2 < 0:
            return "turning_down"
        if all(values[i] >= values[i - 1] for i in range(1, len(values))):
            return "rising"
        if all(values[i] <= values[i - 1] for i in range(1, len(values))):
            return "falling"
        return "mixed"
    delta = values[-1] - values[-2]
    if delta > delta_thr:
        return "rising"
    if delta < -delta_thr:
        return "falling"
    return "flat"


def resolve_harness_reading_signals(
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Derive MSS recovery flags from today's intraday scans."""
    cfg = reading_signals_cfg(settings)
    if not cfg.get("enabled", True):
        return {"reading_available": False}

    try:
        from agent_reach.daily_run.intraday import load_state
        from agent_reach.daily_run.intraday_scan_filters import scans_for_trend_detection

        st = load_state()
    except Exception:
        return {"reading_available": False}

    if len(st.scans) < 2:
        return {"reading_available": False, "scan_count": len(st.scans)}

    session_scans = scans_for_trend_detection(st.scans)
    if not session_scans:
        return {"reading_available": False}

    lookback_mss = _lookback_mss_from_scans(st.scans, settings)
    trend = _trend_from_scans(session_scans, settings)

    latest_mss = float(session_scans[-1].get("mss_final", 0))
    session_values = [float(s.get("mss_final", 0)) for s in session_scans]
    session_low = min(session_values) if session_values else latest_mss
    delta_from_low = latest_mss - session_low

    min_mss = float(cfg["recovery_min_mss"])
    min_lookback = float(cfg["recovery_min_lookback"])
    min_delta = float(cfg["recovery_min_delta"])
    allowed_trends = {str(x) for x in cfg.get("recovery_trends") or ()}

    trend_confirmed = (
        lookback_mss >= min_lookback
        and latest_mss >= min_mss
        and trend in allowed_trends
    )
    v_recovery = latest_mss >= min_mss and delta_from_low >= min_delta and trend in allowed_trends
    from agent_reach.daily_run.defensive_trim_guards import mixed_early_mss_recovery

    mixed_recovery = mixed_early_mss_recovery(
        trend=trend,
        lookback_mss=lookback_mss,
        latest_mss=latest_mss,
        delta_from_low=delta_from_low,
        settings=settings,
    )
    mss_recovery = bool(trend_confirmed or v_recovery or mixed_recovery)

    return {
        "reading_available": True,
        "scan_count": len(st.scans),
        "lookback_mss": round(float(lookback_mss), 2),
        "latest_mss": round(latest_mss, 2),
        "session_low_mss": round(session_low, 2),
        "delta_from_low": round(delta_from_low, 2),
        "trend": trend,
        "mss_recovery": mss_recovery,
        "mixed_early_recovery": mixed_recovery,
        "recovery_macro_veto": float(cfg["recovery_macro_veto"]),
        "recovery_aggressive_entry": float(cfg["recovery_aggressive_entry"]),
    }


def merge_reading_into_trade_signals(
    memory_signals: dict[str, Any],
    reading: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Blend live readings with memory-derived flags (readings can lift stale defense)."""
    cfg = reading_signals_cfg(settings)
    out = dict(memory_signals)
    if not cfg.get("enabled", True) or not reading.get("reading_available"):
        return out

    out["reading_available"] = True
    out["reading_lookback_mss"] = reading.get("lookback_mss")
    out["reading_latest_mss"] = reading.get("latest_mss")
    out["reading_trend"] = reading.get("trend")
    out["mss_recovery"] = bool(reading.get("mss_recovery"))

    if not reading.get("mss_recovery") or not cfg.get("suppress_defensive_on_recovery", True):
        return out

    memory_defensive = bool(memory_signals.get("defensive_trim"))
    if not memory_defensive:
        return out

    if memory_signals.get("pnl_target_miss"):
        if memory_signals.get("mss_forecast_miss"):
            out["reading_suppressed_mss_miss"] = True
            out["mss_forecast_miss"] = False
            out["defensive_trim"] = True
        return out

    out["reading_suppressed_defensive"] = True
    out["defensive_trim"] = False
    out["mss_forecast_miss"] = False
    out["macro_warming"] = True
    return out


def macro_warming_memory_line(reading: dict[str, Any]) -> str:
    lookback = reading.get("lookback_mss")
    trend = reading.get("trend") or "?"
    latest = reading.get("latest_mss")
    low = reading.get("session_low_mss")
    return (
        f"宏观回暖：读数驱动 Lookback MSS {lookback:.1f} / 最新 {latest:.1f} "
        f"（低点 {low:.1f}）趋势 {trend}，解除 stale 防御阈值"
    )


def apply_reading_harness_refinement(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist macro warming to harness memory at close when readings confirm recovery."""
    cfg = reading_signals_cfg(settings)
    reading = resolve_harness_reading_signals(settings)
    if not reading.get("mss_recovery"):
        return {"skipped": True, "reason": "no_mss_recovery"}
    if not cfg.get("persist_macro_warming_on_close", True):
        return {"skipped": True, "reason": "persist_disabled"}

    from agent_reach.daily_run.harness_skill_base import apply_skill_refinement

    line = macro_warming_memory_line(reading)
    return apply_skill_refinement(
        "reading_signals",
        {
            "memory": [line, "宏观回暖"],
            "policy": [],
            "playbook": [],
            "plan": [],
            "summary": (
                f"reading mss_recovery lookback={reading.get('lookback_mss')} "
                f"trend={reading.get('trend')}"
            ),
        },
        settings=settings,
        enabled_flag="reading_signals",
    )
