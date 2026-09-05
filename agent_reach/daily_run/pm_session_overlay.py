# -*- coding: utf-8
"""Persist midday AM session state and tighten/loosen afternoon intraday thresholds."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.intraday_scan_filters import is_midday_anchor_scan
from agent_reach.daily_run.trade_calendar import is_afternoon_session, today_shanghai


def pm_session_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict(((settings or {}).get("midday") or {}).get("pm_session") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "weak_am_trends": tuple(str(x) for x in (raw.get("weak_am_trends") or ("falling", "turning_down"))),
        "weak_am_mss_delta": float(raw.get("weak_am_mss_delta", -5.0)),
        "halfday_loss_pct": float(raw.get("halfday_loss_pct", -0.3)),
        "red_anomaly_count": int(raw.get("red_anomaly_count", 2)),
        "aggressive_entry_delta": float(raw.get("aggressive_entry_delta", 3.0)),
        "macro_veto_delta": float(raw.get("macro_veto_delta", 2.0)),
        "trade_every_n_delta": int(raw.get("trade_every_n_delta", 1)),
        "supportive_am_trends": tuple(
            str(x) for x in (raw.get("supportive_am_trends") or ("rising", "turning_up"))
        ),
        "supportive_am_mss_delta": float(raw.get("supportive_am_mss_delta", 5.0)),
        "supportive_aggressive_entry_delta": float(raw.get("supportive_aggressive_entry_delta", -1.0)),
        "supportive_trade_every_n_delta": int(raw.get("supportive_trade_every_n_delta", -1)),
    }


def pm_session_overlay_active(settings: dict[str, Any]) -> bool:
    runtime = settings.get("harness_runtime") or {}
    block = runtime.get("pm_session") or {}
    return bool(block.get("active"))


def _scan_num(scan_id: object) -> int | None:
    raw = str(scan_id or "").strip().upper()
    if raw.startswith("S") and raw[1:].isdigit():
        return int(raw[1:])
    return None


def am_session_scans(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Morning continuous-session scans (exclude lunch anchor and afternoon scans)."""
    am: list[dict[str, Any]] = []
    for scan in scans or []:
        if is_midday_anchor_scan(scan):
            continue
        src = str(scan.get("source") or "")
        sid = _scan_num(scan.get("scan_id"))
        if sid is not None and sid >= 8:
            continue
        if sid is not None and sid <= 7:
            am.append(scan)
        elif src in {"morning", ""}:
            am.append(scan)
    if am:
        return am
    filtered = [s for s in scans or [] if not is_midday_anchor_scan(s)]
    if len(filtered) >= 2:
        return filtered[: max(1, len(filtered) // 2)]
    return list(filtered)


def compute_am_session_state(
    scans: list[dict[str, Any]],
    *,
    settings: dict[str, Any],
    halfday_pnl_pct: Optional[float] = None,
    red_anomaly_count: int = 0,
    lookback_mss: Optional[float] = None,
    anchor_trend: Optional[str] = None,
) -> dict[str, Any]:
    am = am_session_scans(scans)
    am_trend = "insufficient"
    am_mss_delta = 0.0
    if len(am) >= 2:
        from agent_reach.daily_run.intraday_policy import detect_mss_trend

        am_trend = detect_mss_trend(am, settings)
        am_mss_delta = float(am[-1].get("mss_final", 0)) - float(am[0].get("mss_final", 0))
    elif am:
        am_trend = str(anchor_trend or "flat")
        if len(am) >= 1 and lookback_mss is not None:
            am_mss_delta = float(am[-1].get("mss_final", 0)) - float(lookback_mss)
    else:
        am_trend = str(anchor_trend or "insufficient")

    return {
        "am_scan_count": len(am),
        "am_trend": am_trend,
        "am_mss_delta": round(am_mss_delta, 2),
        "halfday_pnl_pct": round(halfday_pnl_pct, 3) if halfday_pnl_pct is not None else None,
        "red_anomaly_count": int(red_anomaly_count),
        "lookback_mss": round(float(lookback_mss), 2) if lookback_mss is not None else None,
    }


def classify_pm_regime(am_state: dict[str, Any], cfg: dict[str, Any]) -> str:
    trend = str(am_state.get("am_trend") or "")
    delta = float(am_state.get("am_mss_delta") or 0.0)
    halfday = am_state.get("halfday_pnl_pct")
    red = int(am_state.get("red_anomaly_count") or 0)

    weak = (
        trend in cfg["weak_am_trends"]
        or delta <= cfg["weak_am_mss_delta"]
        or red >= cfg["red_anomaly_count"]
        or (halfday is not None and float(halfday) <= cfg["halfday_loss_pct"])
    )
    if weak:
        return "defensive"

    supportive = trend in cfg["supportive_am_trends"] and delta >= cfg["supportive_am_mss_delta"]
    if halfday is not None:
        supportive = supportive and float(halfday) > 0
    if supportive:
        return "supportive"
    return "neutral"


def build_pm_session_overlay_payload(
    *,
    scans: list[dict[str, Any]],
    settings: dict[str, Any],
    halfday_pnl_pct: Optional[float] = None,
    red_anomaly_count: int = 0,
    lookback_mss: Optional[float] = None,
    anchor_trend: Optional[str] = None,
) -> dict[str, Any]:
    cfg = pm_session_cfg(settings)
    am_state = compute_am_session_state(
        scans,
        settings=settings,
        halfday_pnl_pct=halfday_pnl_pct,
        red_anomaly_count=red_anomaly_count,
        lookback_mss=lookback_mss,
        anchor_trend=anchor_trend,
    )
    regime = classify_pm_regime(am_state, cfg)
    return {
        "midday_date": today_shanghai().isoformat(),
        "regime": regime,
        "am_state": am_state,
        "enabled": cfg["enabled"],
    }


def load_pm_session_overlay(*, midday_day: Optional[date] = None) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.midday_handoff import load_midday_handoff

    handoff = load_midday_handoff(midday_day=midday_day or today_shanghai())
    if not handoff:
        return None
    block = handoff.get("pm_session_overlay")
    return dict(block) if isinstance(block, dict) else None


def _patch_threshold(
    cfg: dict[str, Any],
    *,
    key: str,
    effective: float,
    source: str = "pm_session",
) -> None:
    from agent_reach.daily_run.harness_policy import threshold_default

    base = threshold_default(cfg, key)
    thresholds = dict(cfg.get("thresholds") or {})
    thresholds[key] = round(float(effective), 2)
    cfg["thresholds"] = thresholds

    runtime = dict(cfg.get("harness_runtime") or {})
    overlay = dict(runtime.get("threshold_overlay") or {})
    overlay[key] = {"base": round(base, 2), "effective": round(float(effective), 2), "source": source}
    runtime["threshold_overlay"] = overlay
    cfg["harness_runtime"] = runtime


def _patch_trade_every_n(cfg: dict[str, Any], *, delta: int, source: str = "pm_session") -> None:
    from agent_reach.daily_run.harness_policy import runtime_int_default

    base = runtime_int_default(cfg, "schedule", "trade_every_n_scans")
    effective = max(1, min(3, int(base) + int(delta)))

    schedule = dict(cfg.get("schedule") or {})
    schedule["trade_every_n_scans"] = effective
    cfg["schedule"] = schedule

    runtime = dict(cfg.get("harness_runtime") or {})
    overlay = dict(runtime.get("runtime_overlay") or {})
    overlay["trade_every_n_scans"] = {"base": int(base), "effective": int(effective), "source": source}
    runtime["runtime_overlay"] = overlay
    cfg["harness_runtime"] = runtime


def _merge_prior_close_regime(regime: str, settings: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]]]:
    from agent_reach.daily_run.quant_calibration import load_prior_close_session_seed, merge_session_regime

    seed = load_prior_close_session_seed(settings=settings)
    if not seed:
        return regime, None
    seed_regime = str(seed.get("regime") or "").strip() or None
    return merge_session_regime(regime, seed_regime), seed


def apply_pm_session_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
    *,
    dt=None,
) -> dict[str, Any]:
    """Backward-compatible alias; unified patching lives in session_overlay."""
    from agent_reach.daily_run.session_overlay import apply_session_overlay

    return apply_session_overlay(settings, scans, dt=dt)


def apply_intraday_session_overlays(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
) -> dict[str, Any]:
    """Forecast miss → unified session overlay (single patch) → intraday rebound."""
    from agent_reach.daily_run.forecast_miss_overlay import apply_forecast_miss_overlay
    from agent_reach.daily_run.intraday_rebound import apply_intraday_rebound_overlay
    from agent_reach.daily_run.session_overlay import apply_session_overlay

    cfg = apply_forecast_miss_overlay(settings, scans)
    cfg = apply_session_overlay(cfg, scans)
    return apply_intraday_rebound_overlay(cfg, scans)
