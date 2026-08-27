# -*- coding: utf-8
"""Harness-evolved thresholds for rejected_strategies.weekly_whatif."""

from __future__ import annotations

import re
from typing import Any, Optional

_WEEKLY_WHATIF_PREFIX = "rejected weekly_whatif最优"
_WEEKLY_WHATIF_RE = re.compile(
    r"rejected weekly_whatif最优："
    r"buy_notional_delta_cny=([\d.]+)\s+"
    r"sell_pnl_delta_cny=([\d.]+)\s+"
    r"optimizer_score_delta_min=([\d.]+)\s+"
    r"friction_pass_min=([\d.]+)\s+"
    r"trend_mismatch_min=([\d.]+)\s+"
    r"intraday_sell_missed_min=([\d.]+)\s+"
    r"deep_loss_lag_count_min=([\d.]+)\s+"
    r"deep_loss_share_delta_min=([\d.]+)\s+"
    r"sell_threshold_missed_min=([\d.]+)\s+"
    r"forecast_divergence_days_min=([\d.]+)\s+"
    r"kronos_blocked_signals_min=([\d.]+)",
    re.IGNORECASE,
)

_WEEKLY_WHATIF_FLOAT_KEYS: tuple[str, ...] = (
    "buy_notional_delta_cny",
    "sell_pnl_delta_cny",
    "optimizer_score_delta_min",
)
_WEEKLY_WHATIF_INT_KEYS: tuple[str, ...] = (
    "friction_pass_min",
    "trend_mismatch_min",
    "intraday_sell_missed_min",
    "deep_loss_lag_count_min",
    "deep_loss_share_delta_min",
    "sell_threshold_missed_min",
    "forecast_divergence_days_min",
    "kronos_blocked_signals_min",
)
_WEEKLY_WHATIF_KEYS: tuple[str, ...] = _WEEKLY_WHATIF_FLOAT_KEYS + _WEEKLY_WHATIF_INT_KEYS

_WEEKLY_WHATIF_BOUNDS: dict[str, tuple[float, float]] = {
    "buy_notional_delta_cny": (1000.0, 20000.0),
    "sell_pnl_delta_cny": (50.0, 2000.0),
    "friction_pass_min": (1.0, 8.0),
    "trend_mismatch_min": (1.0, 8.0),
    "intraday_sell_missed_min": (1.0, 8.0),
    "deep_loss_lag_count_min": (1.0, 5.0),
    "deep_loss_share_delta_min": (50.0, 2000.0),
    "sell_threshold_missed_min": (1.0, 8.0),
    "forecast_divergence_days_min": (1.0, 12.0),
    "optimizer_score_delta_min": (0.0, 0.5),
    "kronos_blocked_signals_min": (1.0, 8.0),
}

_WEEKLY_WHATIF_NEUTRAL: dict[str, float] = {
    "buy_notional_delta_cny": 5000.0,
    "sell_pnl_delta_cny": 200.0,
    "friction_pass_min": 2.0,
    "trend_mismatch_min": 2.0,
    "intraday_sell_missed_min": 2.0,
    "deep_loss_lag_count_min": 1.0,
    "deep_loss_share_delta_min": 100.0,
    "sell_threshold_missed_min": 2.0,
    "forecast_divergence_days_min": 3.0,
    "optimizer_score_delta_min": 0.05,
    "kronos_blocked_signals_min": 2.0,
}


def _rejected_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("rejected_strategies") or {})


def _weekly_whatif_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = dict(_rejected_section(settings).get("weekly_whatif") or {})
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def weekly_whatif_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = dict(_rejected_section(settings).get("weekly_whatif") or {})
    merged = dict(_WEEKLY_WHATIF_NEUTRAL)
    for key in _WEEKLY_WHATIF_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _WEEKLY_WHATIF_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _WEEKLY_WHATIF_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    return out


def _format_policy_value(key: str, value: float) -> str:
    if key in _WEEKLY_WHATIF_INT_KEYS:
        return str(int(round(float(value))))
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def format_weekly_whatif_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = [f"{key}={_format_policy_value(key, ratios[key])}" for key in _WEEKLY_WHATIF_KEYS if key in ratios]
    if len(parts) < len(_WEEKLY_WHATIF_KEYS):
        return ""
    line = f"{_WEEKLY_WHATIF_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_weekly_whatif_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _WEEKLY_WHATIF_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_WEEKLY_WHATIF_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_weekly_whatif_policy_line(blob)
        if parsed:
            return parsed
    return None


def _scale_int_policy(merged: dict[str, float], key: str, delta: float) -> None:
    lo, hi = _WEEKLY_WHATIF_BOUNDS[key]
    merged[key] = round(max(lo, min(hi, float(merged.get(key, _WEEKLY_WHATIF_NEUTRAL[key])) + delta)), 3)


def _scale_float_policy(merged: dict[str, float], key: str, factor: float) -> None:
    lo, hi = _WEEKLY_WHATIF_BOUNDS[key]
    base = float(merged.get(key, _WEEKLY_WHATIF_NEUTRAL[key]))
    merged[key] = round(max(lo, min(hi, base * factor)), 3)


def _apply_weekly_whatif_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "盈利周证伪库仍入库", settings=settings):
        for key in _WEEKLY_WHATIF_INT_KEYS:
            _scale_int_policy(merged, key, 1.0)
        _scale_float_policy(merged, "buy_notional_delta_cny", 1.15)
        _scale_float_policy(merged, "sell_pnl_delta_cny", 1.15)
        _scale_float_policy(merged, "optimizer_score_delta_min", 1.2)
    if _overlay_has_phrase(state, "亏损周证伪库漏检", settings=settings):
        for key in _WEEKLY_WHATIF_INT_KEYS:
            _scale_int_policy(merged, key, -0.5)
        _scale_float_policy(merged, "buy_notional_delta_cny", 0.9)
        _scale_float_policy(merged, "sell_pnl_delta_cny", 0.85)
        _scale_float_policy(merged, "optimizer_score_delta_min", 0.85)
    if _overlay_has_phrase(state, "证伪库当周入库偏多", settings=settings):
        for key in ("friction_pass_min", "intraday_sell_missed_min", "kronos_blocked_signals_min"):
            _scale_int_policy(merged, key, 1.0)
        _scale_float_policy(merged, "buy_notional_delta_cny", 1.1)
    if _overlay_has_phrase(state, "macro 需 what-if 佐证", settings=settings):
        _scale_int_policy(merged, "friction_pass_min", 0.0)
        _scale_int_policy(merged, "intraday_sell_missed_min", 0.0)
    return merged


def apply_weekly_whatif_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _weekly_whatif_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    for key, val in optimal.items():
        merged[key] = val
    return True


def resolve_harness_weekly_whatif_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = weekly_whatif_policy_base(settings)
    if _weekly_whatif_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_weekly_whatif_signal_evolution(merged, state, settings=settings)
    apply_weekly_whatif_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _weekly_whatif_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _weekly_whatif_mode(cfg) == "fixed":
        return _clamp_policy(weekly_whatif_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("weekly_whatif_policy")
    if isinstance(cached, dict) and cached:
        merged = weekly_whatif_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _WEEKLY_WHATIF_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(weekly_whatif_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_weekly_whatif_policy(load_harness(), settings=cfg)


def weekly_whatif_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_weekly_whatif_policy(settings).get(key, _WEEKLY_WHATIF_NEUTRAL.get(key, 0.0)))


def weekly_whatif_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Effective rejected_strategies config for weekly refresh (harness-evolved thresholds)."""
    rejected = _rejected_section(settings)
    policy = _weekly_whatif_policy(settings)
    sec = dict(rejected.get("weekly_whatif") or {})
    require_macro = sec.get("require_whatif_for_macro", True)
    return {
        "harness_evolve": rejected.get("harness_evolve", True),
        "weekly_refresh": rejected.get("weekly_refresh", True),
        "active_week_only": rejected.get("active_week_only", True),
        "archive_expired": rejected.get("archive_expired", True),
        "auto_add_from_weekly": rejected.get("auto_add_from_weekly", True),
        "require_whatif_for_macro": require_macro is not False,
        "buy_notional_delta_cny": float(policy["buy_notional_delta_cny"]),
        "sell_pnl_delta_cny": float(policy["sell_pnl_delta_cny"]),
        "friction_pass_min": int(policy["friction_pass_min"]),
        "trend_mismatch_min": int(policy["trend_mismatch_min"]),
        "intraday_sell_missed_min": int(policy["intraday_sell_missed_min"]),
        "deep_loss_lag_count_min": int(policy["deep_loss_lag_count_min"]),
        "deep_loss_share_delta_min": int(policy["deep_loss_share_delta_min"]),
        "sell_threshold_missed_min": int(
            policy.get("sell_threshold_missed_min", policy["intraday_sell_missed_min"])
        ),
        "forecast_divergence_days_min": int(policy["forecast_divergence_days_min"]),
        "optimizer_score_delta_min": float(policy["optimizer_score_delta_min"]),
        "kronos_blocked_signals_min": int(policy["kronos_blocked_signals_min"]),
    }


def harness_weekly_whatif_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _WEEKLY_WHATIF_KEYS:
        base_val = float(base_policy.get(key, _WEEKLY_WHATIF_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.001:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
