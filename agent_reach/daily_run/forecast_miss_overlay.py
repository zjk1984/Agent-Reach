# -*- coding: utf-8
"""Intraweek forecast MSS miss streak → mss_forecast.base_spread overlay."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def forecast_miss_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("week_forecast") or {})
    return {
        "enabled": raw.get("intraday_miss_overlay", True) is not False,
        "min_miss_streak": int(raw.get("miss_streak_min_days", 2)),
        "base_spread_delta": int(raw.get("miss_streak_base_spread_delta", 2)),
        "max_base_spread": int(raw.get("miss_streak_max_base_spread", 14)),
    }


def forecast_mss_miss_streak(*, as_of: Optional[date] = None) -> int:
    """Trailing consecutive MSS range misses in the active week forecast."""
    from agent_reach.daily_run.week_forecast import load_active_forecast

    d = as_of or today_shanghai()
    forecast = load_active_forecast(d)
    if not forecast:
        return 0
    trading_days = [str(x) for x in (forecast.get("trading_days") or [])]
    actuals = forecast.get("actuals") or {}
    streak = 0
    for ds in reversed(trading_days):
        if ds > d.isoformat():
            continue
        row = actuals.get(ds)
        if not row:
            # Schedule gap / no close verify — exclude from miss streak (run_guard playbook).
            continue
        mss_hit = row.get("mss_hit")
        if mss_hit is False:
            streak += 1
        elif mss_hit is True:
            break
        else:
            break
    return streak


def apply_forecast_miss_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]] | None = None,
    *,
    dt=None,
) -> dict[str, Any]:
    """Widen intraday MSS forecast band after consecutive close_review MSS misses."""
    _ = scans, dt
    cfg = forecast_miss_cfg(settings)
    if not cfg["enabled"]:
        return settings

    streak = forecast_mss_miss_streak()
    hit_rate_bonus = 0
    try:
        from agent_reach.daily_run.quant_calibration import forecast_hit_rate_gate

        hit_ok, _detail = forecast_hit_rate_gate(settings=settings)
        if not hit_ok:
            raw_q = dict((settings or {}).get("quant_calibration") or {})
            hit_rate_bonus = int(raw_q.get("forecast_miss_hit_rate_spread_delta", 2))
    except Exception:
        hit_rate_bonus = 0

    if streak < cfg["min_miss_streak"] and hit_rate_bonus <= 0:
        return settings

    from agent_reach.daily_run.harness_policy import forecast_int_default

    out = deepcopy(settings)
    base = forecast_int_default(out, "base_spread")
    delta_steps = max(streak, 1 if hit_rate_bonus else 0)
    effective = min(
        cfg["max_base_spread"],
        base + cfg["base_spread_delta"] * delta_steps + hit_rate_bonus,
    )
    if effective <= base:
        return settings

    forecast = dict(out.get("mss_forecast") or {})
    forecast["base_spread"] = int(effective)
    out["mss_forecast"] = forecast

    runtime = dict(out.get("harness_runtime") or {})
    runtime["forecast_miss"] = {
        "active": True,
        "miss_streak": streak,
        "hit_rate_spread_bonus": hit_rate_bonus,
        "base_spread": int(effective),
        "base_before": int(base),
        "optimize_hint": "python3 -m agent_reach.cli daily-run optimize (forecast_calibrate)",
    }
    overlay = dict(runtime.get("forecast_overlay") or {})
    overlay["base_spread"] = {
        "base": int(base),
        "effective": int(effective),
        "source": "forecast_miss_streak",
    }
    runtime["forecast_overlay"] = overlay
    out["harness_runtime"] = runtime
    return out
