# -*- coding: utf-8
"""Harness-evolved Xueqiu hot-stock hit-rate overlay thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_XUEQIU_PREFIX = "xueqiu_hit最优"
_XUEQIU_RE = re.compile(
    r"xueqiu_hit最优："
    r"xueqiu_hit_low_rate=([\d.]+)\s+"
    r"xueqiu_hit_high_rate=([\d.]+)\s+"
    r"xueqiu_hit_overlay_min_samples=([\d.]+)\s+"
    r"xueqiu_hit_overlay_min_misses=([\d.]+)\s+"
    r"xueqiu_hit_overlay_min_hits=([\d.]+)",
    re.IGNORECASE,
)

_XUEQIU_FLOAT_KEYS: tuple[str, ...] = ("xueqiu_hit_low_rate", "xueqiu_hit_high_rate")
_XUEQIU_INT_KEYS: tuple[str, ...] = (
    "xueqiu_hit_overlay_min_samples",
    "xueqiu_hit_overlay_min_misses",
    "xueqiu_hit_overlay_min_hits",
)
_XUEQIU_KEYS: tuple[str, ...] = _XUEQIU_FLOAT_KEYS + _XUEQIU_INT_KEYS

_XUEQIU_BOUNDS: dict[str, tuple[float, float]] = {
    "xueqiu_hit_low_rate": (0.2, 0.55),
    "xueqiu_hit_high_rate": (0.45, 0.85),
    "xueqiu_hit_overlay_min_samples": (2.0, 12.0),
    "xueqiu_hit_overlay_min_misses": (2.0, 10.0),
    "xueqiu_hit_overlay_min_hits": (2.0, 10.0),
}

_XUEQIU_NEUTRAL: dict[str, float] = {
    "xueqiu_hit_low_rate": 0.4,
    "xueqiu_hit_high_rate": 0.6,
    "xueqiu_hit_overlay_min_samples": 3.0,
    "xueqiu_hit_overlay_min_misses": 3.0,
    "xueqiu_hit_overlay_min_hits": 3.0,
}


def _macro_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("macro_collector") or {})


def _xueqiu_hit_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _macro_section(settings)
    mode = str(sec.get("xueqiu_hit_mode") or sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def xueqiu_hit_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _macro_section(settings)
    merged = dict(_XUEQIU_NEUTRAL)
    for key in _XUEQIU_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _XUEQIU_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _XUEQIU_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    if "xueqiu_hit_low_rate" in out and "xueqiu_hit_high_rate" in out:
        if out["xueqiu_hit_low_rate"] >= out["xueqiu_hit_high_rate"]:
            out["xueqiu_hit_high_rate"] = min(
                _XUEQIU_BOUNDS["xueqiu_hit_high_rate"][1],
                out["xueqiu_hit_low_rate"] + 0.1,
            )
    return out


def format_xueqiu_hit_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = []
    for key in _XUEQIU_FLOAT_KEYS:
        if key in ratios:
            parts.append(f"{key}={float(ratios[key]):.2f}")
    for key in _XUEQIU_INT_KEYS:
        if key in ratios:
            parts.append(f"{key}={int(round(float(ratios[key])))}")
    line = f"{_XUEQIU_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_xueqiu_hit_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _XUEQIU_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_XUEQIU_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_xueqiu_hit_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_xueqiu_hit_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "defensive", settings=settings) and _overlay_has_phrase(
        state, "hit_rate", settings=settings
    ):
        merged["xueqiu_hit_low_rate"] = min(
            float(merged.get("xueqiu_hit_low_rate", 0.4)) + 0.05,
            _XUEQIU_BOUNDS["xueqiu_hit_low_rate"][1],
        )
        merged["xueqiu_hit_overlay_min_misses"] = max(
            float(merged.get("xueqiu_hit_overlay_min_misses", 3.0)) - 1.0,
            _XUEQIU_BOUNDS["xueqiu_hit_overlay_min_misses"][0],
        )
    if _overlay_has_phrase(state, "offensive", settings=settings) and _overlay_has_phrase(
        state, "hit_rate", settings=settings
    ):
        merged["xueqiu_hit_high_rate"] = max(
            float(merged.get("xueqiu_hit_high_rate", 0.6)) - 0.05,
            _XUEQIU_BOUNDS["xueqiu_hit_high_rate"][0],
        )
        merged["xueqiu_hit_overlay_min_hits"] = max(
            float(merged.get("xueqiu_hit_overlay_min_hits", 3.0)) - 1.0,
            _XUEQIU_BOUNDS["xueqiu_hit_overlay_min_hits"][0],
        )
    if _overlay_has_phrase(state, "雪球热股", settings=settings) or _overlay_has_phrase(
        state, "xueqiu", settings=settings
    ):
        merged["xueqiu_hit_overlay_min_samples"] = max(
            float(merged.get("xueqiu_hit_overlay_min_samples", 3.0)),
            4.0,
        )
    return merged


def apply_xueqiu_hit_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _xueqiu_hit_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_xueqiu_hit_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = xueqiu_hit_policy_base(settings)
    if _xueqiu_hit_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_xueqiu_hit_signal_evolution(merged, state, settings=settings)
    apply_xueqiu_hit_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _xueqiu_hit_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _xueqiu_hit_mode(cfg) == "fixed":
        return _clamp_policy(xueqiu_hit_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("xueqiu_hit_policy")
    if isinstance(cached, dict) and cached:
        merged = xueqiu_hit_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _XUEQIU_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(xueqiu_hit_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_xueqiu_hit_policy(load_harness(), settings=cfg)


def xueqiu_hit_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_xueqiu_hit_policy(settings).get(key, _XUEQIU_NEUTRAL.get(key, 0.0)))


def xueqiu_hit_threshold_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _macro_section(settings)
    policy = _xueqiu_hit_policy(settings)
    return {
        **sec,
        "xueqiu_hit_mode": _xueqiu_hit_mode(settings),
        "xueqiu_hit_harness_evolve": sec.get("xueqiu_hit_harness_evolve", True),
        "xueqiu_hit_low_rate": float(policy["xueqiu_hit_low_rate"]),
        "xueqiu_hit_high_rate": float(policy["xueqiu_hit_high_rate"]),
        "xueqiu_hit_overlay_min_samples": int(round(float(policy["xueqiu_hit_overlay_min_samples"]))),
        "xueqiu_hit_overlay_min_misses": int(round(float(policy["xueqiu_hit_overlay_min_misses"]))),
        "xueqiu_hit_overlay_min_hits": int(round(float(policy["xueqiu_hit_overlay_min_hits"]))),
    }


def harness_xueqiu_hit_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _XUEQIU_KEYS:
        base_val = float(base_policy.get(key, _XUEQIU_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.001:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
