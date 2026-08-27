# -*- coding: utf-8
"""Harness-evolved expert_consensus drift and score cutoff thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_EXPERT_PREFIX = "expert_consensus最优"
_EXPERT_RE = re.compile(
    r"expert_consensus最优："
    r"mss_drift_threshold=([\d.]+)\s+"
    r"low_score_cutoff=([\d.]+)\s+"
    r"high_score_cutoff=([\d.]+)\s+"
    r"max_mss_drift_flags=([\d.]+)",
    re.IGNORECASE,
)

_EXPERT_FLOAT_KEYS: tuple[str, ...] = (
    "mss_drift_threshold",
    "low_score_cutoff",
    "high_score_cutoff",
)
_EXPERT_INT_KEYS: tuple[str, ...] = ("max_mss_drift_flags",)
_EXPERT_KEYS: tuple[str, ...] = _EXPERT_FLOAT_KEYS + _EXPERT_INT_KEYS

_EXPERT_BOUNDS: dict[str, tuple[float, float]] = {
    "mss_drift_threshold": (6.0, 20.0),
    "low_score_cutoff": (30.0, 50.0),
    "high_score_cutoff": (55.0, 75.0),
    "max_mss_drift_flags": (2.0, 8.0),
}

_EXPERT_NEUTRAL: dict[str, float] = {
    "mss_drift_threshold": 12.0,
    "low_score_cutoff": 42.0,
    "high_score_cutoff": 62.0,
    "max_mss_drift_flags": 4.0,
}


def _expert_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("expert_consensus") or {})


def _expert_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _expert_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def expert_consensus_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _expert_section(settings)
    merged = dict(_EXPERT_NEUTRAL)
    for key in _EXPERT_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _EXPERT_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _EXPERT_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    if "low_score_cutoff" in out and "high_score_cutoff" in out:
        if out["low_score_cutoff"] >= out["high_score_cutoff"]:
            out["high_score_cutoff"] = min(_EXPERT_BOUNDS["high_score_cutoff"][1], out["low_score_cutoff"] + 10.0)
    return out


def format_expert_consensus_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = []
    for key in _EXPERT_FLOAT_KEYS:
        if key in ratios:
            parts.append(f"{key}={float(ratios[key]):g}")
    if "max_mss_drift_flags" in ratios:
        parts.append(f"max_mss_drift_flags={int(round(float(ratios['max_mss_drift_flags'])))}")
    line = f"{_EXPERT_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_expert_consensus_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _EXPERT_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_EXPERT_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_expert_consensus_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_expert_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "MSS drift", settings=settings) or _overlay_has_phrase(
        state, "expert_weekly_drift", settings=settings
    ):
        merged["mss_drift_threshold"] = max(
            float(merged.get("mss_drift_threshold", 12.0)) - 1.0,
            _EXPERT_BOUNDS["mss_drift_threshold"][0],
        )
        merged["max_mss_drift_flags"] = min(
            float(merged.get("max_mss_drift_flags", 4.0)) + 1.0,
            _EXPERT_BOUNDS["max_mss_drift_flags"][1],
        )
    if _overlay_has_phrase(state, "expert_weekly_conflicts", settings=settings) or _overlay_has_phrase(
        state, "专家冲突", settings=settings
    ):
        merged["low_score_cutoff"] = min(
            float(merged.get("low_score_cutoff", 42.0)) + 2.0,
            _EXPERT_BOUNDS["low_score_cutoff"][1],
        )
        merged["high_score_cutoff"] = min(
            float(merged.get("high_score_cutoff", 62.0)) + 2.0,
            _EXPERT_BOUNDS["high_score_cutoff"][1],
        )
    if _overlay_has_phrase(state, "identifier 曾阻断", settings=settings):
        merged["low_score_cutoff"] = max(
            float(merged.get("low_score_cutoff", 42.0)) - 1.0,
            _EXPERT_BOUNDS["low_score_cutoff"][0],
        )
    return merged


def apply_expert_consensus_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _expert_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_expert_consensus_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = expert_consensus_policy_base(settings)
    if _expert_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_expert_signal_evolution(merged, state, settings=settings)
    apply_expert_consensus_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _expert_consensus_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _expert_mode(cfg) == "fixed":
        return _clamp_policy(expert_consensus_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("expert_consensus_policy")
    if isinstance(cached, dict) and cached:
        merged = expert_consensus_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _EXPERT_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(expert_consensus_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_expert_consensus_policy(load_harness(), settings=cfg)


def expert_consensus_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_expert_consensus_policy(settings).get(key, _EXPERT_NEUTRAL.get(key, 0.0)))


def expert_consensus_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _expert_section(settings)
    policy = _expert_consensus_policy(settings)
    out = dict(sec)
    out.update(
        {
            "mode": _expert_mode(settings),
            "harness_evolve": sec.get("harness_evolve", True),
            "mss_drift_threshold": float(policy["mss_drift_threshold"]),
            "low_score_cutoff": float(policy["low_score_cutoff"]),
            "high_score_cutoff": float(policy["high_score_cutoff"]),
            "max_mss_drift_flags": int(round(float(policy["max_mss_drift_flags"]))),
        }
    )
    return out


def harness_expert_consensus_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _EXPERT_KEYS:
        base_val = float(base_policy.get(key, _EXPERT_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
