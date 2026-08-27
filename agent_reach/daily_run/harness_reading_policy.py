# -*- coding: utf-8
"""Harness-evolved MSS reading / recovery detection thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_READING_PREFIX = "reading最优"
_READING_RE = re.compile(
    r"reading最优：recovery_min_mss=([\d.]+)\s+recovery_min_lookback=([\d.]+)\s+recovery_macro_veto=([\d.]+)",
    re.IGNORECASE,
)

_EVOLVED_READING_KEYS: tuple[str, ...] = (
    "recovery_min_mss",
    "recovery_min_lookback",
    "recovery_macro_veto",
)

_READING_NEUTRAL: dict[str, float] = {
    "recovery_min_mss": 52.0,
    "recovery_min_lookback": 52.0,
    "recovery_macro_veto": 38.0,
}

_READING_BOUNDS: dict[str, tuple[float, float]] = {
    "recovery_min_mss": (48.0, 55.0),
    "recovery_min_lookback": (48.0, 55.0),
    "recovery_macro_veto": (35.0, 42.0),
}


def _reading_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    harness = dict((settings or {}).get("harness") or {})
    return dict(harness.get("reading_signals") or {})


def reading_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _reading_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def reading_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _reading_section(settings)
    merged = dict(_READING_NEUTRAL)
    for key in _EVOLVED_READING_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    return merged


def _clamp_reading_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _EVOLVED_READING_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _READING_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 2)
    for key in _EVOLVED_READING_KEYS:
        if key not in out:
            out[key] = float(_READING_NEUTRAL[key])
    return out


def format_reading_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    line = (
        f"{_READING_PREFIX}："
        f"recovery_min_mss={float(ratios.get('recovery_min_mss', 52.0)):.2f} "
        f"recovery_min_lookback={float(ratios.get('recovery_min_lookback', 52.0)):.2f} "
        f"recovery_macro_veto={float(ratios.get('recovery_macro_veto', 38.0)):.2f}"
    )
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_reading_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _READING_RE.search(str(text or ""))
    if not match:
        return None
    return _clamp_reading_policy(
        {
            "recovery_min_mss": float(match.group(1)),
            "recovery_min_lookback": float(match.group(2)),
            "recovery_macro_veto": float(match.group(3)),
        }
    )


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_reading_policy_line(blob)
        if parsed:
            return parsed
    return None


def _memory_trade_flags(state: Any, *, settings: dict[str, Any]) -> dict[str, bool]:
    """Memory-only trade flags — avoids resolve_harness_trade_signals recursion."""
    from agent_reach.daily_run.harness_policy import (
        _MSS_MISS_PHRASES,
        _collect_text_blobs,
        _has_deviation_signal,
        _overlay_sources,
    )

    sources = _overlay_sources(settings)
    blobs = _collect_text_blobs(state, sources=sources, kind="memory", settings=settings)
    blobs += _collect_text_blobs(state, sources=sources, kind="policy", settings=settings)
    mss_miss = any(any(p in blob for p in _MSS_MISS_PHRASES) for blob in blobs)
    deviation = _has_deviation_signal(state, sources=sources, settings=settings)
    pnl_hit = any("盈亏目标达成" in blob for blob in blobs)
    pnl_miss = any("盈亏目标未达" in blob for blob in blobs)
    return {
        "mss_forecast_miss": mss_miss,
        "defensive_trim": mss_miss or deviation or pnl_miss,
        "pnl_target_hit": pnl_hit,
        "pnl_target_miss": pnl_miss,
    }


def _apply_reading_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase, evolution_mode

    signals = _memory_trade_flags(state, settings=settings)

    def _ease(mss_floor: float, lookback_floor: float, veto_ceiling: float) -> None:
        if evolution_mode(settings, "recovery_min_mss") == "harness":
            merged["recovery_min_mss"] = min(
                float(merged.get("recovery_min_mss", 52.0)), mss_floor
            )
        if evolution_mode(settings, "recovery_min_lookback") == "harness":
            merged["recovery_min_lookback"] = min(
                float(merged.get("recovery_min_lookback", 52.0)), lookback_floor
            )
        if evolution_mode(settings, "recovery_macro_veto") == "harness":
            merged["recovery_macro_veto"] = max(
                float(merged.get("recovery_macro_veto", 38.0)), veto_ceiling
            )

    def _tighten(mss_ceiling: float, lookback_ceiling: float, veto_floor: float) -> None:
        if evolution_mode(settings, "recovery_min_mss") == "harness":
            merged["recovery_min_mss"] = max(
                float(merged.get("recovery_min_mss", 52.0)), mss_ceiling
            )
        if evolution_mode(settings, "recovery_min_lookback") == "harness":
            merged["recovery_min_lookback"] = max(
                float(merged.get("recovery_min_lookback", 52.0)), lookback_ceiling
            )
        if evolution_mode(settings, "recovery_macro_veto") == "harness":
            merged["recovery_macro_veto"] = min(
                float(merged.get("recovery_macro_veto", 38.0)), veto_floor
            )

    if signals.get("defensive_trim") or signals.get("mss_forecast_miss"):
        _ease(50.0, 50.0, 39.0)
    if signals.get("pnl_target_miss"):
        _ease(49.5, 49.5, 39.5)
    if signals.get("pnl_target_hit"):
        _tighten(53.0, 53.0, 36.0)
    if _overlay_has_phrase(state, "达进攻阈值未落账", settings=settings):
        _ease(49.5, 49.5, 40.0)
    if _overlay_has_phrase(state, "反弹起点", settings=settings) or _overlay_has_phrase(
        state, "未释放买入", settings=settings
    ):
        _ease(49.0, 49.0, 40.0)
    if _overlay_has_phrase(state, "过早买入", settings=settings) or _overlay_has_phrase(
        state, "减少频繁调仓", settings=settings
    ):
        _tighten(54.0, 54.0, 35.0)
    if _overlay_has_phrase(state, "趋势误判", settings=settings):
        _ease(50.0, 50.0, 39.0)
    if _overlay_has_phrase(state, "宏观回暖", settings=settings):
        _ease(49.0, 49.0, 40.0)
    return merged


def apply_reading_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if reading_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    from agent_reach.daily_run.harness_policy import evolution_mode

    for key in _EVOLVED_READING_KEYS:
        if evolution_mode(settings, key) == "harness" and key in optimal:
            merged[key] = optimal[key]
    return True


def resolve_harness_reading_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    base = reading_policy_base(settings)
    merged = dict(base)
    if reading_mode(settings) != "harness":
        return _clamp_reading_policy(merged)
    from agent_reach.daily_run.harness_policy import (
        _overlay_enabled,
        _restore_fixed_evolution_keys,
    )

    if not _overlay_enabled(settings):
        return _clamp_reading_policy(merged)
    merged = _apply_reading_signal_evolution(merged, state, settings=settings)
    apply_reading_llm_optimal_to_policy(merged, state, settings=settings)
    merged = _restore_fixed_evolution_keys(merged, base, settings, _EVOLVED_READING_KEYS)
    return _clamp_reading_policy(merged)


def _reading_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if reading_mode(cfg) == "fixed":
        return _clamp_reading_policy(reading_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("reading_policy")
    if isinstance(cached, dict) and cached:
        merged = reading_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _EVOLVED_READING_KEYS})
        return _clamp_reading_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_reading_policy(reading_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_reading_policy(load_harness(), settings=cfg)


def reading_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_reading_policy(settings).get(key, _READING_NEUTRAL.get(key, 0.0)))


def reading_effective_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _reading_section(settings)
    policy = _reading_policy(settings)
    out = dict(sec)
    out["mode"] = reading_mode(settings)
    for key in _EVOLVED_READING_KEYS:
        out[key] = float(policy[key])
    return out


def harness_reading_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _EVOLVED_READING_KEYS:
        base_val = float(base_policy.get(key, _READING_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
