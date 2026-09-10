# -*- coding: utf-8
"""Backtrader-inspired execution simulation: fill timing, slippage, volume cap."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_policy import (
    friction_commission_rate_default,
    friction_slippage_rate_default,
)


def execution_sim_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = dict((settings or {}).get("execution_sim") or {})
    trading = dict((settings or {}).get("trading") or {})
    root.setdefault("fill_timing", trading.get("fill_timing") or "close")
    root.setdefault("max_bar_participation_pct", trading.get("max_bar_participation_pct", 0))
    root.setdefault("apply_slippage_in_whatif", True)
    root.setdefault("apply_slippage_live", True)
    return root


def execution_sim_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return execution_sim_cfg(settings).get("enabled", True) is not False


def resolve_fill_timing(settings: Optional[dict[str, Any]] = None) -> str:
    timing = str(execution_sim_cfg(settings).get("fill_timing") or "close").strip().lower()
    return timing if timing in ("close", "next_open") else "close"


def max_bar_participation_pct(settings: Optional[dict[str, Any]] = None) -> float:
    raw = execution_sim_cfg(settings).get("max_bar_participation_pct", 0)
    try:
        return max(0.0, float(raw or 0))
    except (TypeError, ValueError):
        return 0.0


def apply_slippage(price: float, *, side: str, slippage_rate: float) -> float:
    rate = max(0.0, float(slippage_rate or 0))
    if side == "buy":
        return round(float(price) * (1.0 + rate), 4)
    return round(float(price) * (1.0 - rate), 4)


def cap_shares_by_bar_volume(
    shares: int,
    row: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[int, bool]:
    """Limit order size to max % of bar volume (Backtrader FixedBarPerc-style)."""
    pct = max_bar_participation_pct(settings)
    if pct <= 0 or shares <= 0:
        return shares, False
    volume = row.get("volume")
    try:
        bar_volume = float(volume)
    except (TypeError, ValueError):
        return shares, False
    if bar_volume <= 0:
        return shares, False
    cap = max(1, int(bar_volume * pct / 100.0))
    if shares > cap:
        return cap, True
    return shares, False


def sim_execution_price(
    row: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    *,
    side: str,
    settings: Optional[dict[str, Any]] = None,
    with_slippage: bool = True,
) -> tuple[Optional[float], dict[str, Any]]:
    """Resolve fill price with optional slippage and metadata."""
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    code = _normalize_code(str(row.get("code") or ""))
    merged = {**enriched.get(code, {}), **row}
    timing = resolve_fill_timing(settings)
    meta: dict[str, Any] = {"fill_timing": timing}
    base: Optional[float] = None
    if timing == "next_open":
        for key in ("open", "today_open", "open_price"):
            val = merged.get(key)
            if val is not None:
                try:
                    base = float(val)
                    meta["price_source"] = key
                    break
                except (TypeError, ValueError):
                    continue
    if base is None:
        for key in ("price", "cost", "close"):
            val = merged.get(key)
            if val is not None:
                try:
                    base = float(val)
                    meta["price_source"] = key
                    break
                except (TypeError, ValueError):
                    continue
    if base is None or base <= 0:
        return None, meta
    if with_slippage and execution_sim_enabled(settings):
        cfg = execution_sim_cfg(settings)
        use_slip = bool(cfg.get("apply_slippage_live", True))
        if use_slip:
            slip = friction_slippage_rate_default(settings or {})
            base = apply_slippage(base, side=side, slippage_rate=slip)
            meta["slippage_rate"] = slip
    meta["fill_price"] = base
    return base, meta


def sim_trade_shares(
    shares: int,
    row: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    *,
    side: str,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[int, dict[str, Any]]:
    capped, volume_limited = cap_shares_by_bar_volume(shares, row, settings=settings)
    meta = {"volume_limited": volume_limited}
    if volume_limited:
        meta["max_bar_participation_pct"] = max_bar_participation_pct(settings)
    return capped, meta


def whatif_execution_price(
    row: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    *,
    side: str,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    cfg = execution_sim_cfg(settings)
    apply_slip = bool(cfg.get("apply_slippage_in_whatif", True))
    price, _ = sim_execution_price(row, enriched, side=side, settings=settings, with_slippage=apply_slip)
    return price


def whatif_commission(gross: float, settings: Optional[dict[str, Any]] = None) -> float:
    rate = friction_commission_rate_default(settings or {})
    return round(float(gross) * rate, 2)
