# -*- coding: utf-8
"""Harness-evolved finance tolerance thresholds across finance_* sections."""

from __future__ import annotations

import re
from typing import Any, Optional

_FINANCE_PREFIX = "finance_tolerance最优"
_FINANCE_RE = re.compile(
    r"finance_tolerance最优："
    r"reconcile_tolerance_cny=([\d.]+)\s+"
    r"variance_tolerance_cny=([\d.]+)\s+"
    r"variance_materiality_cny=([\d.]+)\s+"
    r"amount_tolerance_cny=([\d.]+)\s+"
    r"statement_materiality_cny=([\d.]+)\s+"
    r"tie_tolerance_cny=([\d.]+)",
    re.IGNORECASE,
)

_FINANCE_KEYS: tuple[str, ...] = (
    "reconcile_tolerance_cny",
    "variance_tolerance_cny",
    "variance_materiality_cny",
    "amount_tolerance_cny",
    "statement_materiality_cny",
    "tie_tolerance_cny",
)

_FINANCE_BOUNDS: dict[str, tuple[float, float]] = {
    "reconcile_tolerance_cny": (0.1, 10.0),
    "variance_tolerance_cny": (0.5, 20.0),
    "variance_materiality_cny": (100.0, 5000.0),
    "amount_tolerance_cny": (0.1, 10.0),
    "statement_materiality_cny": (100.0, 5000.0),
    "tie_tolerance_cny": (0.5, 20.0),
}

_FINANCE_NEUTRAL: dict[str, float] = {
    "reconcile_tolerance_cny": 1.0,
    "variance_tolerance_cny": 5.0,
    "variance_materiality_cny": 1000.0,
    "amount_tolerance_cny": 1.0,
    "statement_materiality_cny": 1000.0,
    "tie_tolerance_cny": 5.0,
}


def _finance_mode(settings: Optional[dict[str, Any]]) -> str:
    close = dict((settings or {}).get("finance_close") or {})
    mode = str(close.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def finance_tolerance_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    close = dict(cfg.get("finance_close") or {})
    variance = dict(cfg.get("finance_variance") or {})
    ledger = dict(cfg.get("finance_ledger") or {})
    statements = dict(cfg.get("finance_statements") or {})
    merged = dict(_FINANCE_NEUTRAL)
    if "reconcile_tolerance_cny" in close:
        merged["reconcile_tolerance_cny"] = float(close["reconcile_tolerance_cny"])
    if "variance_tolerance_cny" in close:
        merged["variance_tolerance_cny"] = float(close["variance_tolerance_cny"])
    if "variance_materiality_cny" in close:
        merged["variance_materiality_cny"] = float(close["variance_materiality_cny"])
    if "variance_tolerance_cny" in variance:
        merged["variance_tolerance_cny"] = float(variance["variance_tolerance_cny"])
    if "variance_materiality_cny" in variance:
        merged["variance_materiality_cny"] = float(variance["variance_materiality_cny"])
    if "amount_tolerance_cny" in ledger:
        merged["amount_tolerance_cny"] = float(ledger["amount_tolerance_cny"])
    if "materiality_cny" in statements:
        merged["statement_materiality_cny"] = float(statements["materiality_cny"])
    if "tie_tolerance_cny" in statements:
        merged["tie_tolerance_cny"] = float(statements["tie_tolerance_cny"])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _FINANCE_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _FINANCE_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    return out


def format_finance_tolerance_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = [f"{key}={float(ratios[key]):g}" for key in _FINANCE_KEYS if key in ratios]
    line = f"{_FINANCE_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_finance_tolerance_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _FINANCE_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_FINANCE_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_finance_tolerance_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_finance_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "bridge 残差", settings=settings) or _overlay_has_phrase(
        state, "finance_variance", settings=settings
    ):
        merged["variance_tolerance_cny"] = max(
            float(merged.get("variance_tolerance_cny", 5.0)) * 0.9,
            _FINANCE_BOUNDS["variance_tolerance_cny"][0],
        )
    if _overlay_has_phrase(state, "reconcile", settings=settings) or _overlay_has_phrase(
        state, "对账", settings=settings
    ):
        merged["reconcile_tolerance_cny"] = max(
            float(merged.get("reconcile_tolerance_cny", 1.0)) * 0.8,
            _FINANCE_BOUNDS["reconcile_tolerance_cny"][0],
        )
    if _overlay_has_phrase(state, "ledger", settings=settings) or _overlay_has_phrase(
        state, "台账", settings=settings
    ):
        merged["amount_tolerance_cny"] = max(
            float(merged.get("amount_tolerance_cny", 1.0)) * 0.8,
            _FINANCE_BOUNDS["amount_tolerance_cny"][0],
        )
    return merged


def apply_finance_tolerance_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _finance_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_finance_tolerance_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = finance_tolerance_policy_base(settings)
    if _finance_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_finance_signal_evolution(merged, state, settings=settings)
    apply_finance_tolerance_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _finance_tolerance_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _finance_mode(cfg) == "fixed":
        return _clamp_policy(finance_tolerance_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("finance_tolerance_policy")
    if isinstance(cached, dict) and cached:
        merged = finance_tolerance_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _FINANCE_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(finance_tolerance_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_finance_tolerance_policy(load_harness(), settings=cfg)


def finance_tolerance_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_finance_tolerance_policy(settings).get(key, _FINANCE_NEUTRAL.get(key, 0.0)))


def finance_tolerance_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    return dict(_finance_tolerance_policy(settings))


def apply_finance_tolerance_overlay(settings: dict[str, Any]) -> dict[str, Any]:
    """Merge harness-evolved tolerances into finance_* sections."""
    cfg = dict(settings)
    policy = _finance_tolerance_policy(cfg)
    close = dict(cfg.get("finance_close") or {})
    close["mode"] = _finance_mode(cfg)
    close["reconcile_tolerance_cny"] = float(policy["reconcile_tolerance_cny"])
    close["variance_tolerance_cny"] = float(policy["variance_tolerance_cny"])
    close["variance_materiality_cny"] = float(policy["variance_materiality_cny"])
    cfg["finance_close"] = close
    variance = dict(cfg.get("finance_variance") or {})
    variance["variance_tolerance_cny"] = float(policy["variance_tolerance_cny"])
    variance["variance_materiality_cny"] = float(policy["variance_materiality_cny"])
    cfg["finance_variance"] = variance
    ledger = dict(cfg.get("finance_ledger") or {})
    ledger["amount_tolerance_cny"] = float(policy["amount_tolerance_cny"])
    cfg["finance_ledger"] = ledger
    statements = dict(cfg.get("finance_statements") or {})
    statements["materiality_cny"] = float(policy["statement_materiality_cny"])
    statements["tie_tolerance_cny"] = float(policy["tie_tolerance_cny"])
    cfg["finance_statements"] = statements
    return cfg


def harness_finance_tolerance_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _FINANCE_KEYS:
        base_val = float(base_policy.get(key, _FINANCE_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
