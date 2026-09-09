# -*- coding: utf-8
"""Guards for memory-driven defensive trim + proportional deep-loss sells."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_DEFENSIVE_TRIM_NEUTRAL: dict[str, Any] = {
    "enabled": True,
    "max_symbol_change_pct": 3.0,
    "require_mss_pullback_pts": 2.0,
    "memory_sell_ratio": 0.35,
    "short_hold_sell_ratio": 0.25,
    "short_hold_grace_days": 1,
    "recovery_mixed_lookback_slack": 2.0,
    "recovery_mixed_mss_slack": 1.0,
    "recovery_mixed_delta_factor": 0.5,
    "once_per_symbol_per_day": True,
    "block_sell_in_recovery_zone": True,
    "persist_macro_warming_intraday": True,
    "block_sell_near_day_low": True,
    "near_day_low_tolerance_pct": 0.5,
    "near_day_low_bypass_deep_loss": True,
}


def defensive_trim_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    intraday = dict((settings or {}).get("intraday") or {})
    block = dict(intraday.get("defensive_trim") or {})
    out = {**_DEFENSIVE_TRIM_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", True))
    return out


def _recovery_thresholds(settings: dict[str, Any]) -> dict[str, float]:
    from agent_reach.daily_run.harness_reading_signals import reading_signals_cfg

    cfg = reading_signals_cfg(settings)
    return {
        "recovery_min_mss": float(cfg.get("recovery_min_mss", 52.0)),
        "recovery_min_lookback": float(cfg.get("recovery_min_lookback", 52.0)),
        "recovery_min_delta": float(cfg.get("recovery_min_delta", 5.0)),
        "recovery_macro_veto": float(cfg.get("recovery_macro_veto", 38.0)),
    }


def defensive_trim_blocked_by_recovery_zone(
    settings: dict[str, Any],
    *,
    lookback_mss: float,
    trade_signals: dict[str, Any],
) -> Optional[str]:
    """Block memory-driven trim when live MSS is already in macro-warming territory."""
    cfg = defensive_trim_cfg(settings)
    if not cfg.get("block_sell_in_recovery_zone", True):
        return None
    if trade_signals.get("pnl_target_miss"):
        return None
    if trade_signals.get("mss_recovery") or trade_signals.get("macro_warming"):
        return "盘中 MSS 回暖已解除 stale 防御，记忆驱动减仓暂缓"

    thresholds = _recovery_thresholds(settings)
    min_lookback = thresholds["recovery_min_lookback"]
    if float(lookback_mss) >= min_lookback:
        return (
            f"Lookback MSS {lookback_mss:.0f} ≥ 回暖线 {min_lookback:.0f}，"
            "记忆 MSS 偏离暂不执行防御减仓"
        )
    return None


def _symbol_change_pct(snapshot: dict[str, Any], code: Any) -> Optional[float]:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return None
    for key in ("change_pct",):
        val = snapshot.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    pf = snapshot.get("portfolio") or {}
    for holding in pf.get("holdings") or []:
        if _normalize_code(str(holding.get("code", ""))) != norm:
            continue
        chg = holding.get("change_pct")
        if chg is not None:
            try:
                return float(chg)
            except (TypeError, ValueError):
                pass
    for row in snapshot.get("symbols") or []:
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        chg = row.get("change_pct")
        if chg is not None:
            try:
                return float(chg)
            except (TypeError, ValueError):
                pass
    return None


def _session_mss_stats(settings: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    try:
        from agent_reach.daily_run.intraday import load_state
        from agent_reach.daily_run.intraday_scan_filters import scans_for_trend_detection

        st = load_state()
        session = scans_for_trend_detection(st.scans)
        if not session:
            return None, None
        values = [float(s.get("mss_final", 0)) for s in session]
        return max(values), float(values[-1])
    except Exception:
        return None, None


def _symbol_price_and_day_low(snapshot: dict[str, Any], code: Any) -> tuple[Optional[float], Optional[float]]:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return None, None

    price: Optional[float] = None
    day_low: Optional[float] = None

    for key in ("price",):
        val = snapshot.get(key)
        if val is not None:
            try:
                price = float(val)
            except (TypeError, ValueError):
                pass

    pf = snapshot.get("portfolio") or {}
    for holding in pf.get("holdings") or []:
        if _normalize_code(str(holding.get("code", ""))) != norm:
            continue
        if price is None:
            for pk in ("price",):
                val = holding.get(pk)
                if val is not None:
                    try:
                        price = float(val)
                    except (TypeError, ValueError):
                        pass
        for lk in ("day_low",):
            val = holding.get(lk)
            if val is not None:
                try:
                    day_low = float(val)
                except (TypeError, ValueError):
                    pass

    for row in snapshot.get("symbols") or []:
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        if price is None:
            val = row.get("price")
            if val is not None:
                try:
                    price = float(val)
                except (TypeError, ValueError):
                    pass
        if day_low is None:
            val = row.get("day_low")
            if val is not None:
                try:
                    day_low = float(val)
                except (TypeError, ValueError):
                    pass

    return price, day_low


def defensive_trim_blocked_by_near_day_low(
    settings: dict[str, Any],
    *,
    code: Any,
    snapshot: dict[str, Any],
) -> Optional[str]:
    """Block proportional trim when price sits at/near the session low (unless deep loss)."""
    cfg = defensive_trim_cfg(settings)
    if not cfg.get("block_sell_near_day_low", True):
        return None

    price, day_low = _symbol_price_and_day_low(snapshot, code)
    if price is None or day_low is None or day_low <= 0:
        return None

    tolerance_pct = float(cfg.get("near_day_low_tolerance_pct", 0.5))
    distance_pct = (price - day_low) / day_low * 100.0
    if distance_pct > tolerance_pct:
        return None

    if cfg.get("near_day_low_bypass_deep_loss", True):
        from agent_reach.daily_run.portfolio_manager import symbol_is_deep_loss_holding

        if symbol_is_deep_loss_holding(snapshot, settings, str(code or "")):
            return None

    return (
        f"现价 {price:.2f} 距日内低点 {day_low:.2f} ≤{tolerance_pct:.1f}%，"
        "防御减仓暂缓以免卖在日内低点"
    )


def defensive_trim_blocked_by_strength(
    settings: dict[str, Any],
    *,
    trend: str,
    code: Any,
    snapshot: dict[str, Any],
) -> Optional[str]:
    """Avoid trimming into intraday strength unless MSS rolls over from session high."""
    cfg = defensive_trim_cfg(settings)
    if not cfg.get("enabled", True):
        return None

    weak_trends = {"falling", "turning_down"}
    if str(trend or "") in weak_trends:
        return None

    change_pct = _symbol_change_pct(snapshot, code)
    max_chg = float(cfg.get("max_symbol_change_pct", 1.0))
    if change_pct is not None and change_pct > max_chg:
        session_high, latest_mss = _session_mss_stats(settings)
        pullback_pts = float(cfg.get("require_mss_pullback_pts", 2.0))
        if session_high is not None and latest_mss is not None:
            pullback = session_high - latest_mss
            if pullback >= pullback_pts:
                return None
        return (
            f"标的今日 {change_pct:+.2f}% 强于阈值 {max_chg:.1f}%，"
            f"趋势 {trend} 且无 MSS 自高点回落 ≥{pullback_pts:.0f} 点，暂缓防御减仓"
        )
    return None


def defensive_trim_already_applied(
    prior_trades: Optional[list[dict[str, Any]]],
    code: Any,
) -> bool:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return False
    for trade in prior_trades or []:
        if str(trade.get("action") or "") != "sell":
            continue
        if not trade.get("portfolio_applied"):
            continue
        if _normalize_code(str(trade.get("code") or "")) != norm:
            continue
        reasoning = str(trade.get("reasoning") or "")
        if "防御性减仓" in reasoning or trade.get("defensive_trim"):
            return True
    return False


def defensive_trim_blocked_by_daily_cap(
    settings: dict[str, Any],
    *,
    prior_trades: Optional[list[dict[str, Any]]],
    code: Any,
) -> Optional[str]:
    cfg = defensive_trim_cfg(settings)
    if not cfg.get("once_per_symbol_per_day", True):
        return None
    if defensive_trim_already_applied(prior_trades, code):
        return "今日已执行记忆驱动防御减仓，同标的不再重复 trim"
    return None


def evaluate_defensive_trim_sell(
    settings: dict[str, Any],
    *,
    lookback_mss: float,
    macro_veto: float,
    trend: str,
    trade_signals: dict[str, Any],
    report: dict[str, Any],
    snapshot: dict[str, Any],
    prior_trades: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, Optional[str]]:
    """Return (allow_sell, hold_reason)."""
    from agent_reach.daily_run.intraday_policy import defensive_trim_allows_sell

    cfg = defensive_trim_cfg(settings)
    if not cfg.get("enabled", True):
        return False, None
    if not trade_signals.get("defensive_trim"):
        return False, None
    if not defensive_trim_allows_sell(
        settings,
        lookback_mss=lookback_mss,
        macro_veto=macro_veto,
        trend=trend,
    ):
        return False, None

    for blocker in (
        lambda: defensive_trim_blocked_by_recovery_zone(
            settings, lookback_mss=lookback_mss, trade_signals=trade_signals
        ),
        lambda: defensive_trim_blocked_by_daily_cap(
            settings, prior_trades=prior_trades, code=report.get("code")
        ),
        lambda: defensive_trim_blocked_by_strength(
            settings,
            trend=trend,
            code=report.get("code"),
            snapshot=snapshot,
        ),
        lambda: defensive_trim_blocked_by_near_day_low(
            settings,
            code=report.get("code"),
            snapshot=snapshot,
        ),
    ):
        reason = blocker()
        if reason:
            return False, reason
    return True, None


def defensive_trim_effective_sell_ratio(
    settings: dict[str, Any],
    holding: dict[str, Any],
    *,
    is_deep_loss: bool,
    base_ratio: float,
) -> float:
    """Cap proportional trim for memory defense (lighter on short holds)."""
    runtime = settings.get("harness_runtime") or {}
    trade_signals = runtime.get("trade_signals") or {}
    if not trade_signals.get("defensive_trim"):
        return base_ratio

    cfg = defensive_trim_cfg(settings)
    memory_ratio = float(cfg.get("memory_sell_ratio", 0.35))
    short_ratio = float(cfg.get("short_hold_sell_ratio", 0.25))
    short_grace = int(cfg.get("short_hold_grace_days", 1))

    from agent_reach.daily_run.harness_policy import runtime_int_default
    from agent_reach.daily_run.portfolio_manager import effective_days_held

    lock_days = runtime_int_default(settings, "trading", "holding_lock_days")
    days = effective_days_held(holding, settings=settings)
    if days <= lock_days + short_grace:
        return min(float(base_ratio), short_ratio)
    if is_deep_loss:
        return min(float(base_ratio), memory_ratio)
    return min(float(base_ratio), memory_ratio)


def mixed_early_mss_recovery(
    *,
    trend: str,
    lookback_mss: float,
    latest_mss: float,
    delta_from_low: float,
    settings: Optional[dict[str, Any]] = None,
) -> bool:
    """Morning-friendly recovery when trend is mixed but MSS is already elevated."""
    if trend != "mixed":
        return False
    cfg = defensive_trim_cfg(settings)
    thresholds = _recovery_thresholds(settings or {})
    lookback_slack = float(cfg.get("recovery_mixed_lookback_slack", 2.0))
    mss_slack = float(cfg.get("recovery_mixed_mss_slack", 1.0))
    delta_factor = float(cfg.get("recovery_mixed_delta_factor", 0.5))
    min_lookback = thresholds["recovery_min_lookback"] - lookback_slack
    min_mss = thresholds["recovery_min_mss"] - mss_slack
    min_delta = thresholds["recovery_min_delta"] * delta_factor
    return (
        float(lookback_mss) >= min_lookback
        and float(latest_mss) >= min_mss
        and float(delta_from_low) >= min_delta
    )


def maybe_persist_intraday_macro_warming(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Write macro warming to harness memory during intraday when recovery confirms."""
    cfg = defensive_trim_cfg(settings)
    if not cfg.get("persist_macro_warming_intraday", True):
        return {"skipped": True, "reason": "persist_disabled"}

    from agent_reach.daily_run.harness import load_harness
    from agent_reach.daily_run.harness_reading_signals import (
        apply_reading_harness_refinement,
        resolve_harness_reading_signals,
    )

    reading = resolve_harness_reading_signals(settings)
    if not reading.get("mss_recovery"):
        return {"skipped": True, "reason": "no_mss_recovery"}

    state = load_harness()
    blobs = [
        str(entry.content or "")
        for entry in (state.entries.get("memory") or {}).values()
    ]
    if any("宏观回暖" in blob for blob in blobs):
        return {"skipped": True, "reason": "already_warming"}

    return apply_reading_harness_refinement(settings=settings)
