# -*- coding: utf-8
"""Harness-evolved optimizer grid search space (macro_veto / aggressive_entry / objective)."""

from __future__ import annotations

import re
from typing import Any, Optional

_OBJECTIVE_CHOICES = ("sharpe", "excess_return", "total_return", "win_rate", "sharpe_proxy")

_OPTIMIZER_GRID_PREFIX = "optimizer grid最优"
_OPTIMIZER_GRID_RE = re.compile(
    r"optimizer grid最优："
    r"macro_veto_low=([\d.]+)\s+"
    r"macro_veto_high=([\d.]+)\s+"
    r"aggressive_entry_low=([\d.]+)\s+"
    r"aggressive_entry_high=([\d.]+)\s+"
    r"grid_points=([\d.]+)\s+"
    r"default_objective=(\w+)",
    re.IGNORECASE,
)

_OPTIMIZER_GRID_FLOAT_KEYS: tuple[str, ...] = (
    "macro_veto_low",
    "macro_veto_high",
    "aggressive_entry_low",
    "aggressive_entry_high",
    "grid_points",
)
_OPTIMIZER_GRID_KEYS: tuple[str, ...] = _OPTIMIZER_GRID_FLOAT_KEYS + ("default_objective",)

_OPTIMIZER_GRID_BOUNDS: dict[str, tuple[float, float]] = {
    "macro_veto_low": (30.0, 50.0),
    "macro_veto_high": (35.0, 55.0),
    "aggressive_entry_low": (40.0, 60.0),
    "aggressive_entry_high": (45.0, 65.0),
    "grid_points": (3.0, 8.0),
}

_OPTIMIZER_GRID_NEUTRAL: dict[str, float | str] = {
    "macro_veto_low": 38.0,
    "macro_veto_high": 45.0,
    "aggressive_entry_low": 48.0,
    "aggressive_entry_high": 55.0,
    "grid_points": 4.0,
    "default_objective": "sharpe",
}


def _optimizer_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("optimizer") or {})


def _optimizer_grid_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _optimizer_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def _grid_from_config(sec: dict[str, Any], key: str, fallback: list[float]) -> list[float]:
    raw = sec.get(key)
    if isinstance(raw, list) and raw:
        return [float(x) for x in raw]
    return list(fallback)


def _derive_grid(low: float, high: float, points: float) -> list[float]:
    count = max(2, int(round(float(points))))
    lo = float(min(low, high))
    hi = float(max(low, high))
    if count <= 1 or abs(hi - lo) < 1e-9:
        return [round(lo, 2)]
    step = (hi - lo) / (count - 1)
    return [round(lo + i * step, 2) for i in range(count)]


def optimizer_grid_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _optimizer_section(settings)
    merged: dict[str, Any] = dict(_OPTIMIZER_GRID_NEUTRAL)
    veto_grid = _grid_from_config(sec, "macro_veto_grid", [38, 40, 42, 45])
    entry_grid = _grid_from_config(sec, "aggressive_entry_grid", [48, 50, 52, 55])
    if veto_grid:
        merged["macro_veto_low"] = float(min(veto_grid))
        merged["macro_veto_high"] = float(max(veto_grid))
        merged["grid_points"] = float(len(veto_grid))
    if entry_grid:
        merged["aggressive_entry_low"] = float(min(entry_grid))
        merged["aggressive_entry_high"] = float(max(entry_grid))
    objective = str(sec.get("default_objective") or merged["default_objective"]).strip().lower()
    if objective in _OBJECTIVE_CHOICES:
        merged["default_objective"] = objective
    for key in _OPTIMIZER_GRID_FLOAT_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    if sec.get("default_objective"):
        obj = str(sec["default_objective"]).strip().lower()
        if obj in _OBJECTIVE_CHOICES:
            merged["default_objective"] = obj
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _OPTIMIZER_GRID_FLOAT_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _OPTIMIZER_GRID_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    obj = str(raw.get("default_objective") or _OPTIMIZER_GRID_NEUTRAL["default_objective"]).strip().lower()
    out["default_objective"] = obj if obj in _OBJECTIVE_CHOICES else str(_OPTIMIZER_GRID_NEUTRAL["default_objective"])
    if "macro_veto_low" in out and "macro_veto_high" in out and out["macro_veto_low"] > out["macro_veto_high"]:
        out["macro_veto_low"], out["macro_veto_high"] = out["macro_veto_high"], out["macro_veto_low"]
    if (
        "aggressive_entry_low" in out
        and "aggressive_entry_high" in out
        and out["aggressive_entry_low"] > out["aggressive_entry_high"]
    ):
        out["aggressive_entry_low"], out["aggressive_entry_high"] = (
            out["aggressive_entry_high"],
            out["aggressive_entry_low"],
        )
    return out


def format_optimizer_grid_policy_line(ratios: dict[str, Any], *, rationale: str = "") -> str:
    parts = []
    for key in _OPTIMIZER_GRID_FLOAT_KEYS:
        if key in ratios:
            val = ratios[key]
            text = str(int(round(float(val)))) if key == "grid_points" else f"{float(val):g}"
            parts.append(f"{key}={text}")
    obj = str(ratios.get("default_objective") or _OPTIMIZER_GRID_NEUTRAL["default_objective"])
    parts.append(f"default_objective={obj}")
    line = f"{_OPTIMIZER_GRID_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_optimizer_grid_policy_line(text: str) -> Optional[dict[str, Any]]:
    match = _OPTIMIZER_GRID_RE.search(str(text or ""))
    if not match:
        return None
    raw = {
        key: float(match.group(i + 1))
        for i, key in enumerate(_OPTIMIZER_GRID_FLOAT_KEYS)
    }
    raw["default_objective"] = str(match.group(len(_OPTIMIZER_GRID_FLOAT_KEYS) + 1)).strip().lower()
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_optimizer_grid_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_optimizer_grid_signal_evolution(
    merged: dict[str, Any],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, Any]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "回测网格偏窄", settings=settings):
        merged["macro_veto_low"] = float(merged.get("macro_veto_low", 38.0)) - 1.0
        merged["macro_veto_high"] = float(merged.get("macro_veto_high", 45.0)) + 1.0
        merged["aggressive_entry_low"] = float(merged.get("aggressive_entry_low", 48.0)) - 1.0
        merged["aggressive_entry_high"] = float(merged.get("aggressive_entry_high", 55.0)) + 1.0
    if _overlay_has_phrase(state, "optimizer underperforms", settings=settings) or _overlay_has_phrase(
        state, "runtime_underperforms", settings=settings
    ):
        merged["default_objective"] = "excess_return"
        merged["grid_points"] = max(float(merged.get("grid_points", 4.0)), 5.0)
    if _overlay_has_phrase(state, "optimizer grid:", settings=settings):
        merged["grid_points"] = max(float(merged.get("grid_points", 4.0)), 4.0)
    return merged


def apply_optimizer_grid_llm_optimal_to_policy(
    merged: dict[str, Any],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _optimizer_grid_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_optimizer_grid_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, Any]:
    merged = optimizer_grid_policy_base(settings)
    if _optimizer_grid_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_optimizer_grid_signal_evolution(merged, state, settings=settings)
    apply_optimizer_grid_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _optimizer_grid_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = settings or {}
    if _optimizer_grid_mode(cfg) == "fixed":
        return _clamp_policy(optimizer_grid_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("optimizer_grid_policy")
    if isinstance(cached, dict) and cached:
        merged = optimizer_grid_policy_base(cfg)
        merged.update({k: cached[k] for k in _OPTIMIZER_GRID_KEYS if k in cached})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(optimizer_grid_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_optimizer_grid_policy(load_harness(), settings=cfg)


def optimizer_grid_policy_default(settings: dict[str, Any], key: str) -> Any:
    policy = _optimizer_grid_policy(settings)
    if key == "default_objective":
        return str(policy.get("default_objective", _OPTIMIZER_GRID_NEUTRAL["default_objective"]))
    return float(policy.get(key, _OPTIMIZER_GRID_NEUTRAL.get(key, 0.0)))


def optimizer_grid_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Effective optimizer section for grid_search_optimize."""
    sec = _optimizer_section(settings)
    policy = _optimizer_grid_policy(settings)
    if _optimizer_grid_mode(settings) == "fixed":
        macro_veto_grid = _grid_from_config(sec, "macro_veto_grid", [38, 40, 42, 45])
        aggressive_entry_grid = _grid_from_config(sec, "aggressive_entry_grid", [48, 50, 52, 55])
    else:
        points = float(policy.get("grid_points", 4.0))
        macro_veto_grid = _derive_grid(
            float(policy["macro_veto_low"]),
            float(policy["macro_veto_high"]),
            points,
        )
        aggressive_entry_grid = _derive_grid(
            float(policy["aggressive_entry_low"]),
            float(policy["aggressive_entry_high"]),
            points,
        )
    mss_weight_grid = sec.get("mss_weight_grid")
    return {
        "harness_evolve": sec.get("harness_evolve", True),
        "mode": _optimizer_grid_mode(settings),
        "macro_veto_grid": macro_veto_grid,
        "aggressive_entry_grid": aggressive_entry_grid,
        "default_objective": str(policy.get("default_objective", "sharpe")),
        "mss_weight_grid": mss_weight_grid,
        "macro_veto_low": float(policy["macro_veto_low"]),
        "macro_veto_high": float(policy["macro_veto_high"]),
        "aggressive_entry_low": float(policy["aggressive_entry_low"]),
        "aggressive_entry_high": float(policy["aggressive_entry_high"]),
        "grid_points": int(round(float(policy.get("grid_points", 4.0)))),
    }


def harness_optimizer_grid_overlay_meta(
    base_policy: dict[str, Any],
    effective_policy: dict[str, Any],
) -> dict[str, Any]:
    changed: dict[str, dict[str, Any]] = {}
    for key in _OPTIMIZER_GRID_KEYS:
        base_val = base_policy.get(key, _OPTIMIZER_GRID_NEUTRAL.get(key))
        eff_val = effective_policy.get(key, base_val)
        if str(base_val) != str(eff_val):
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
