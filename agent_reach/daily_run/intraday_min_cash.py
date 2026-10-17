# -*- coding: utf-8
"""Relax harness min_cash when MSS attack threshold met and TSP retreat is off."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.technical_scenario_watch import technical_watch_cfg


def tsp_retreat_blocks_min_cash_relax(
    settings: dict[str, Any],
    *,
    live_breadth: Optional[dict[str, Any]] = None,
) -> bool:
    """True when intraday TSP retreat brake would block aggressive deploy."""
    try:
        from agent_reach.daily_run.tsp.intraday_sentinel import check_intraday_retreat_risk

        blocked, _reason = check_intraday_retreat_risk(
            settings,
            live_breadth=live_breadth,
        )
        return bool(blocked)
    except Exception:
        return False


def effective_intraday_min_cash_ratio(
    settings: dict[str, Any],
    *,
    lookback_mss: float,
    live_breadth: Optional[dict[str, Any]] = None,
) -> tuple[float, Optional[str]]:
    """
    Return (effective_min_cash_ratio, relax_note).

    When Lookback MSS ≥ rebound_mss_level and TSP retreat is not active, lower the
    register min_cash cap by relax_delta (technical_watch.min_cash_ratio_cap).
    """
    from agent_reach.daily_run.harness_policy import min_cash_ratio_default

    base = float(min_cash_ratio_default(settings))
    watch = technical_watch_cfg(settings)
    cap_cfg = dict(watch.get("min_cash_ratio_cap") or {})
    if cap_cfg.get("enabled") is False:
        return base, None

    rebound_mss = float(cap_cfg.get("rebound_mss_level", 55.0))
    relax_delta = float(cap_cfg.get("relax_delta", 0.02))
    register_floor = float(cap_cfg.get("register_min_cash_ratio", 0.5))
    attack_floor = float(cap_cfg.get("attack_min_cash_ratio", 0.35))

    if float(lookback_mss) + 1e-9 < rebound_mss:
        return base, None
    if tsp_retreat_blocks_min_cash_relax(settings, live_breadth=live_breadth):
        return base, None

    pinned = max(base, register_floor)
    relaxed = max(0.0, min(pinned, register_floor) - relax_delta)
    if base + 1e-9 >= register_floor:
        relaxed = min(relaxed, attack_floor)
    effective = min(base, relaxed) if relaxed + 1e-9 < base else base
    if effective + 1e-9 >= base:
        return base, None
    note = (
        f"Lookback MSS {lookback_mss:.0f}≥{rebound_mss:.0f} 且非 TSP 退潮，"
        f"min_cash {base:.0%}→{effective:.0%}"
    )
    return effective, note
