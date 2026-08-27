# -*- coding: utf-8
"""Harness-evolved intraday rebound detection thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_REBOUND_PREFIX = "rebound最优"
_REBOUND_RE = re.compile(
    r"rebound最优：min_mss_delta=([\d.]+)\s+min_latest_mss=([\d.]+)",
    re.IGNORECASE,
)

_EVOLVED_REBOUND_KEYS: tuple[str, ...] = ("min_mss_delta", "min_latest_mss")

_REBOUND_NEUTRAL: dict[str, float] = {
    "min_mss_delta": 3.0,
    "min_latest_mss": 50.0,
}

_REBOUND_BOUNDS: dict[str, tuple[float, float]] = {
    "min_mss_delta": (1.5, 6.0),
    "min_latest_mss": (45.0, 55.0),
}


def _rebound_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict(((settings or {}).get("intraday") or {}).get("rebound") or {})


def rebound_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _rebound_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def rebound_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _rebound_section(settings)
    merged = dict(_REBOUND_NEUTRAL)
    if "min_mss_delta" in sec:
        merged["min_mss_delta"] = float(sec["min_mss_delta"])
    if "min_latest_mss" in sec:
        merged["min_latest_mss"] = float(sec["min_latest_mss"])
    return merged


def _clamp_rebound_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _EVOLVED_REBOUND_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _REBOUND_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 2)
    for key in _EVOLVED_REBOUND_KEYS:
        if key not in out:
            out[key] = float(_REBOUND_NEUTRAL[key])
    return out


def format_rebound_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    line = (
        f"{_REBOUND_PREFIX}："
        f"min_mss_delta={float(ratios.get('min_mss_delta', 3.0)):.2f} "
        f"min_latest_mss={float(ratios.get('min_latest_mss', 50.0)):.2f}"
    )
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_rebound_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _REBOUND_RE.search(str(text or ""))
    if not match:
        return None
    return _clamp_rebound_policy(
        {
            "min_mss_delta": float(match.group(1)),
            "min_latest_mss": float(match.group(2)),
        }
    )


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_rebound_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_rebound_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import (
        _overlay_has_phrase,
        evolution_mode,
        resolve_harness_trade_signals,
    )

    signals = resolve_harness_trade_signals(state, settings=settings)

    def _ease(delta_floor: float, latest_floor: float) -> None:
        if evolution_mode(settings, "min_mss_delta") == "harness":
            merged["min_mss_delta"] = min(float(merged.get("min_mss_delta", 3.0)), delta_floor)
        if evolution_mode(settings, "min_latest_mss") == "harness":
            merged["min_latest_mss"] = min(float(merged.get("min_latest_mss", 50.0)), latest_floor)

    def _tighten(delta_ceiling: float, latest_ceiling: float) -> None:
        if evolution_mode(settings, "min_mss_delta") == "harness":
            merged["min_mss_delta"] = max(float(merged.get("min_mss_delta", 3.0)), delta_ceiling)
        if evolution_mode(settings, "min_latest_mss") == "harness":
            merged["min_latest_mss"] = max(float(merged.get("min_latest_mss", 50.0)), latest_ceiling)

    if signals.get("defensive_trim") or signals.get("mss_forecast_miss"):
        _ease(2.5, 48.0)
    if signals.get("pnl_target_miss"):
        _ease(2.0, 47.0)
    if signals.get("pnl_target_hit"):
        _tighten(3.5, 52.0)
    if _overlay_has_phrase(state, "达进攻阈值未落账", settings=settings):
        _ease(2.0, 47.0)
    if _overlay_has_phrase(state, "反弹起点", settings=settings) or _overlay_has_phrase(
        state, "未释放买入", settings=settings
    ):
        _ease(2.0, 47.0)
    if _overlay_has_phrase(state, "过早买入", settings=settings) or _overlay_has_phrase(
        state, "减少频繁调仓", settings=settings
    ):
        _tighten(4.0, 52.0)
    if _overlay_has_phrase(state, "趋势误判", settings=settings):
        _ease(2.5, 48.5)
    return merged


def apply_rebound_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if rebound_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    from agent_reach.daily_run.harness_policy import evolution_mode

    for key in _EVOLVED_REBOUND_KEYS:
        if evolution_mode(settings, key) == "harness" and key in optimal:
            merged[key] = optimal[key]
    return True


def resolve_harness_rebound_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    base = rebound_policy_base(settings)
    merged = dict(base)
    if rebound_mode(settings) != "harness":
        return _clamp_rebound_policy(merged)
    from agent_reach.daily_run.harness_policy import (
        _overlay_enabled,
        _restore_fixed_evolution_keys,
    )

    if not _overlay_enabled(settings):
        return _clamp_rebound_policy(merged)
    merged = _apply_rebound_signal_evolution(merged, state, settings=settings)
    apply_rebound_llm_optimal_to_policy(merged, state, settings=settings)
    merged = _restore_fixed_evolution_keys(merged, base, settings, _EVOLVED_REBOUND_KEYS)
    return _clamp_rebound_policy(merged)


def _rebound_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if rebound_mode(cfg) == "fixed":
        return _clamp_rebound_policy(rebound_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("rebound_policy")
    if isinstance(cached, dict) and cached:
        merged = rebound_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _EVOLVED_REBOUND_KEYS})
        return _clamp_rebound_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_rebound_policy(rebound_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_rebound_policy(load_harness(), settings=cfg)


def rebound_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_rebound_policy(settings).get(key, _REBOUND_NEUTRAL.get(key, 0.0)))


def rebound_effective_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _rebound_section(settings)
    policy = _rebound_policy(settings)
    out = dict(sec)
    out["mode"] = rebound_mode(settings)
    out["min_mss_delta"] = float(policy["min_mss_delta"])
    out["min_latest_mss"] = float(policy["min_latest_mss"])
    return out


def harness_rebound_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _EVOLVED_REBOUND_KEYS:
        base_val = float(base_policy.get(key, _REBOUND_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
