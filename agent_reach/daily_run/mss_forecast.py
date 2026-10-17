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
