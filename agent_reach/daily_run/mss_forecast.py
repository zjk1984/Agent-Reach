# -*- coding: utf-8
"""Simple MSS range forecast (Monte Carlo lite)."""

from __future__ import annotations

import random
from typing import Any, Optional


def forecast_mss_range(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    simulations: int = 200,
) -> tuple[list[float], dict[str, Any]]:
    """
    Estimate intraday MSS range from current breakdown + volatility hints.

    Returns ([low, high], meta dict).
    """
    cfg = settings.get("mss_forecast", {})
    sims = int(cfg.get("simulations", simulations))
    breakdown = snapshot.get("mss_breakdown") or {}
    weights = settings.get("mss_weights", {})

    base = snapshot.get("mss_final")
    if base is None:
        from agent_reach.daily_run.verdict import compute_mss

        base = compute_mss(breakdown, settings)
    base = float(base)

    from agent_reach.daily_run.harness_policy import forecast_int_default

    vol_hint = _volatility_hint(snapshot)
    spread = float(forecast_int_default(settings, "base_spread")) + vol_hint * float(
        forecast_int_default(settings, "vol_multiplier")
    )
    spread += _emotion_spread_bonus(breakdown, cfg)
    mainline_bonus = _mainline_rotation_spread_bonus(snapshot, cfg)
    spread += mainline_bonus
    technical = breakdown.get("technical")
    if technical is not None:
        try:
            tech_f = float(technical)
            if tech_f >= 70:
                spread += float(cfg.get("technical_high_spread_bonus", 8))
            elif tech_f >= 55:
                spread += float(cfg.get("technical_mid_spread_bonus", 4))
        except (TypeError, ValueError):
            pass

    rng = random.Random(int(base * 100) % 9973)
    samples: list[float] = []
    for _ in range(sims):
        noise = rng.gauss(0, spread / 2)
        factor_noise = sum(
            rng.gauss(0, 3) * float(weights.get(k, 0.25))
            for k in weights
            if k in breakdown
        )
        samples.append(max(0.0, min(100.0, base + noise + factor_noise)))

    samples.sort()
    lo = round(samples[int(sims * 0.15)], 1)
    hi = round(samples[int(sims * 0.85)], 1)
    if lo > hi:
        lo, hi = hi, lo

    meta = {
        "method": "monte_carlo_lite",
        "simulations": sims,
        "base_mss": base,
        "volatility_hint": vol_hint,
        "mainline_rotation_spread_bonus": mainline_bonus,
        "median": round(samples[sims // 2], 1),
    }
    return [lo, hi], meta


def _volatility_hint(snapshot: dict[str, Any]) -> float:
    change = snapshot.get("change_pct")
    if change is not None:
        return min(3.0, abs(float(change)) / 2)
    scans = snapshot.get("mss_intraday_actual") or []
    if len(scans) >= 2:
        return min(3.0, abs(float(scans[-1]) - float(scans[-2])) / 5)
    return 1.0


def _symbol_sector_label(snapshot: dict[str, Any]) -> str:
    for key in ("sector", "industry"):
        val = str(snapshot.get(key) or "").strip()
        if val:
            return val
    code = str(snapshot.get("code") or "").strip()
    pf = snapshot.get("portfolio") or {}
    for holding in pf.get("holdings") or []:
        if not isinstance(holding, dict):
            continue
        if code and str(holding.get("code") or "") != code:
            continue
        for key in ("sector", "industry"):
            val = str(holding.get(key) or "").strip()
            if val:
                return val
    return ""


def _mainline_rotation_spread_bonus(snapshot: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Widen forecast band when symbol sector aligns with live TSP top mainline (rotation days)."""
    if cfg.get("mainline_rotation_enabled", True) is False:
        return 0.0
    bonus = float(cfg.get("mainline_rotation_spread_bonus", 2.0))
    if bonus <= 0:
        return 0.0
    sector = _symbol_sector_label(snapshot)
    if not sector:
        return 0.0
    breadth = snapshot.get("tsp_intraday") or snapshot.get("tsp_breadth") or {}
    mainlines = breadth.get("top_mainlines") or []
    for row in mainlines:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("sector") or "").strip()
        if not name:
            continue
        if name == sector or name in sector or sector in name:
            return bonus
    return 0.0


def _emotion_spread_bonus(breakdown: dict[str, Any], cfg: dict[str, Any]) -> float:
    ref = (breakdown or {}).get("_emotion_fusion_ref") or {}
    rating = str(ref.get("rating") or "")
    if rating == "强":
        return float(cfg.get("emotion_spread_bonus", 10))
    if rating == "弱":
        return float(cfg.get("emotion_weak_spread_bonus", 6))
    return 0.0


def refresh_intraday_mss_range(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
) -> list[float]:
    """Recompute MSS interval from latest breakdown (F4 intraday refresh)."""
    mss_range, _meta = forecast_mss_range(snapshot, settings)
    snapshot["mss_intraday_range"] = mss_range
    return mss_range


def mss_forecast_overrun_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """AR-23: lift intraday verdict ceiling when lookback MSS beats week forecast upper band."""
    intraday = dict((settings or {}).get("intraday") or {})
    raw = dict(intraday.get("mss_forecast_overrun") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "overrun_pts": float(raw.get("overrun_pts", 8)),
        "consecutive_slots": max(1, int(raw.get("consecutive_slots", 2))),
    }


def active_day_mss_forecast_upper(
    settings: Optional[dict[str, Any]] = None,
    *,
    as_of: Optional[Any] = None,
) -> Optional[float]:
    """Upper bound of MSS range from the active week forecast for the trading day."""
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.week_forecast import load_active_forecast

    d = as_of or today_shanghai()
    if hasattr(d, "isoformat"):
        ds = d.isoformat()
    else:
        ds = str(d)[:10]
    forecast = load_active_forecast(d if hasattr(d, "isoformat") else None)
    if not forecast:
        return None
    row = (forecast.get("mss_daily") or {}).get(ds) or {}
    rng = row.get("range")
    if not isinstance(rng, (list, tuple)) or len(rng) < 2:
        return None
    try:
        return float(rng[1])
    except (TypeError, ValueError):
        return None


def lookback_overruns_forecast_upper(
    lookback_mss: float,
    *,
    upper: Optional[float],
    overrun_pts: float,
) -> bool:
    if upper is None:
        return False
    return float(lookback_mss) + 1e-9 >= float(upper) + float(overrun_pts)


def consecutive_forecast_overrun_slots(
    scans: list[dict[str, Any]],
    settings: dict[str, Any],
) -> int:
    """Trailing count of scan slots (same session) with lookback MSS ≥ forecast upper + overrun."""
    cfg = mss_forecast_overrun_cfg(settings)
    if not cfg["enabled"] or not scans:
        return 0
    upper = active_day_mss_forecast_upper(settings)
    if upper is None:
        return 0

    from agent_reach.daily_run.lookback import compute_lookback_mss

    streak = 0
    for end in range(len(scans), 0, -1):
        prefix = scans[:end]
        lb, _detail = compute_lookback_mss(prefix, settings)
        if lookback_overruns_forecast_upper(
            lb,
            upper=upper,
            overrun_pts=cfg["overrun_pts"],
        ):
            streak += 1
        else:
            break
    return streak


def forecast_overrun_ceiling_lifted(
    scans: list[dict[str, Any]],
    settings: dict[str, Any],
) -> bool:
    cfg = mss_forecast_overrun_cfg(settings)
    if not cfg["enabled"]:
        return False
    streak = consecutive_forecast_overrun_slots(scans, settings)
    return streak >= cfg["consecutive_slots"]


def macro_intraday_gating_active(settings: dict[str, Any]) -> bool:
    """True when macro/intraday overlays keep the verdict ceiling at 「观察」 by default."""
    runtime = dict(settings.get("harness_runtime") or {})
    trade_signals = dict(runtime.get("trade_signals") or {})
    if trade_signals.get("defensive_trim") or trade_signals.get("mss_forecast_miss"):
        return True
    for key in ("pm_session", "am_open", "week_open"):
        block = runtime.get(key) or {}
        if not block.get("active"):
            continue
        regime = str(block.get("regime") or "").strip().lower()
        if regime == "defensive":
            return True
    seed = runtime.get("session_seed") or {}
    merged = str(seed.get("merged_regime") or "").strip().lower()
    return merged == "defensive"
