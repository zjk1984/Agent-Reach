# -*- coding: utf-8
"""Harness-evolved data_audit coverage and block flags (close + intraday)."""

from __future__ import annotations

import re
from typing import Any, Optional

_DATA_AUDIT_PREFIX = "data_audit最优"
_DATA_AUDIT_RE = re.compile(
    r"data_audit最优："
    r"min_quote_coverage_pct=([\d.]+)\s+"
    r"block_on_audit_fail=([\d.]+)\s+"
    r"close_block_on_audit_fail=([\d.]+)\s+"
    r"block_on_price_deviation=([\d.]+)",
    re.IGNORECASE,
)

_DATA_AUDIT_FLOAT_KEYS: tuple[str, ...] = ("min_quote_coverage_pct",)
_DATA_AUDIT_BOOL_KEYS: tuple[str, ...] = (
    "block_on_audit_fail",
    "close_block_on_audit_fail",
    "block_on_price_deviation",
)
_DATA_AUDIT_KEYS: tuple[str, ...] = _DATA_AUDIT_FLOAT_KEYS + _DATA_AUDIT_BOOL_KEYS

_DATA_AUDIT_BOUNDS: dict[str, tuple[float, float]] = {
    "min_quote_coverage_pct": (0.5, 1.0),
    "block_on_audit_fail": (0.0, 1.0),
    "close_block_on_audit_fail": (0.0, 1.0),
    "block_on_price_deviation": (0.0, 1.0),
}

_DATA_AUDIT_NEUTRAL: dict[str, float] = {
    "min_quote_coverage_pct": 0.8,
    "block_on_audit_fail": 1.0,
    "close_block_on_audit_fail": 1.0,
    "block_on_price_deviation": 1.0,
}


def _audit_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("data_audit") or {})


def _data_audit_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _audit_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def _bool_to_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return default
    return 1.0 if float(value) > 0.5 else 0.0


def data_audit_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _audit_section(settings)
    merged = dict(_DATA_AUDIT_NEUTRAL)
    if "min_quote_coverage_pct" in sec:
        merged["min_quote_coverage_pct"] = float(sec["min_quote_coverage_pct"])
    merged["block_on_audit_fail"] = _bool_to_float(
        sec.get("block_on_audit_fail"), merged["block_on_audit_fail"]
    )
    merged["close_block_on_audit_fail"] = _bool_to_float(
        sec.get("close_block_on_audit_fail"), merged["close_block_on_audit_fail"]
    )
    merged["block_on_price_deviation"] = _bool_to_float(
        sec.get("block_on_price_deviation"), merged["block_on_price_deviation"]
    )
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _DATA_AUDIT_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _DATA_AUDIT_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    for key in _DATA_AUDIT_BOOL_KEYS:
        if key in out:
            out[key] = 1.0 if float(out[key]) > 0.5 else 0.0
    return out


def format_data_audit_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = [f"min_quote_coverage_pct={float(ratios.get('min_quote_coverage_pct', 0.8)):.2f}"]
    for key in _DATA_AUDIT_BOOL_KEYS:
        if key in ratios:
            parts.append(f"{key}={int(round(float(ratios[key])))}")
    line = f"{_DATA_AUDIT_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_data_audit_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _DATA_AUDIT_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_DATA_AUDIT_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_data_audit_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_data_audit_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "数据审计未通过", settings=settings) or _overlay_has_phrase(
        state, "行情覆盖率", settings=settings
    ):
        merged["min_quote_coverage_pct"] = max(float(merged.get("min_quote_coverage_pct", 0.8)), 0.85)
        merged["close_block_on_audit_fail"] = 1.0
        merged["block_on_audit_fail"] = 1.0
    if _overlay_has_phrase(state, "audit", settings=settings) and _overlay_has_phrase(
        state, "quote", settings=settings
    ):
        merged["min_quote_coverage_pct"] = max(float(merged.get("min_quote_coverage_pct", 0.8)), 0.82)
    if _overlay_has_phrase(state, "价格偏离", settings=settings) or _overlay_has_phrase(
        state, "price_deviation", settings=settings
    ):
        merged["block_on_price_deviation"] = 1.0
    signals = None
    try:
        from agent_reach.daily_run.harness_policy import resolve_harness_trade_signals

        signals = resolve_harness_trade_signals(state, settings=settings)
    except Exception:
        signals = {}
    if signals and signals.get("defensive_trim"):
        merged["close_block_on_audit_fail"] = 1.0
    return merged


def apply_data_audit_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _data_audit_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_data_audit_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = data_audit_policy_base(settings)
    if _data_audit_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_data_audit_signal_evolution(merged, state, settings=settings)
    apply_data_audit_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _data_audit_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _data_audit_mode(cfg) == "fixed":
        return _clamp_policy(data_audit_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("data_audit_policy")
    if isinstance(cached, dict) and cached:
        merged = data_audit_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _DATA_AUDIT_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(data_audit_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_data_audit_policy(load_harness(), settings=cfg)


def data_audit_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_data_audit_policy(settings).get(key, _DATA_AUDIT_NEUTRAL.get(key, 0.0)))


def data_audit_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _audit_section(settings)
    policy = _data_audit_policy(settings)
    return {
        **sec,
        "mode": _data_audit_mode(settings),
        "harness_evolve": sec.get("harness_evolve", True),
        "min_quote_coverage_pct": float(policy["min_quote_coverage_pct"]),
        "block_on_audit_fail": float(policy["block_on_audit_fail"]) > 0.5,
        "close_block_on_audit_fail": float(policy["close_block_on_audit_fail"]) > 0.5,
        "block_on_price_deviation": float(policy["block_on_price_deviation"]) > 0.5,
    }


def harness_data_audit_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _DATA_AUDIT_KEYS:
        base_val = float(base_policy.get(key, _DATA_AUDIT_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
