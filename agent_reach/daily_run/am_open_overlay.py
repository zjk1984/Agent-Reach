# -*- coding: utf-8
"""Persist 08:00 morning analysis and tune morning-session intraday thresholds (S4–S7)."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.pm_session_overlay import (
    _patch_threshold,
    _patch_trade_every_n,
)
from agent_reach.daily_run.trade_calendar import is_morning_session, today_shanghai

_AVOID_VERDICTS = frozenset({"回避", "avoid"})
_BUY_VERDICTS = frozenset({"可做", "buy", "进攻"})
_WATCH_VERDICTS = frozenset({"观察", "watch"})


def am_open_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("morning_open") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "defensive_verdicts": tuple(str(x) for x in (raw.get("defensive_verdicts") or ("回避", "avoid"))),
        "supportive_verdicts": tuple(str(x) for x in (raw.get("supportive_verdicts") or ("可做", "buy"))),
        "high_cash_ratio": float(raw.get("high_cash_ratio", 0.45)),
        "weak_mss_below_veto_buffer": float(raw.get("weak_mss_below_veto_buffer", 0.0)),
        "aggressive_entry_delta": float(raw.get("aggressive_entry_delta", 2.0)),
        "macro_veto_delta": float(raw.get("macro_veto_delta", 2.0)),
        "trade_every_n_delta": int(raw.get("trade_every_n_delta", 1)),
        "supportive_mss_above_aggressive": float(raw.get("supportive_mss_above_aggressive", 0.0)),
        "supportive_aggressive_entry_delta": float(raw.get("supportive_aggressive_entry_delta", -1.0)),
        "supportive_trade_every_n_delta": int(raw.get("supportive_trade_every_n_delta", -1)),
    }


def am_open_overlay_active(settings: dict[str, Any]) -> bool:
    runtime = settings.get("harness_runtime") or {}
    block = runtime.get("am_open") or {}
    return bool(block.get("active"))


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _worst_verdict(verdicts: list[str]) -> str:
    cleaned = [str(v or "").strip() for v in verdicts if str(v or "").strip()]
    if not cleaned:
        return ""
    if any(v in _AVOID_VERDICTS for v in cleaned):
        return next(v for v in cleaned if v in _AVOID_VERDICTS)
    if all(v in _BUY_VERDICTS for v in cleaned):
        return cleaned[0]
    if any(v in _WATCH_VERDICTS for v in cleaned):
        return next(v for v in cleaned if v in _WATCH_VERDICTS)
    return cleaned[0]


def compute_morning_open_state(
    *,
    mss_final: Optional[float] = None,
    verdict: Optional[str] = None,
    blocked: Optional[bool] = None,
    cash_ratio: Optional[float] = None,
    macro_summary: Optional[str] = None,
    audit_passed: Optional[bool] = None,
    gate_passed: Optional[bool] = None,
) -> dict[str, Any]:
    return {
        "mss_final": round(float(mss_final), 2) if mss_final is not None else None,
        "verdict": str(verdict or "").strip() or None,
        "blocked": bool(blocked) if blocked is not None else None,
        "cash_ratio": round(float(cash_ratio), 4) if cash_ratio is not None else None,
        "macro_summary_present": bool(str(macro_summary or "").strip()),
        "audit_passed": audit_passed,
        "gate_passed": gate_passed,
    }


def classify_am_open_regime(state: dict[str, Any], cfg: dict[str, Any], *, settings: dict[str, Any]) -> str:
    from agent_reach.daily_run.harness_policy import aggressive_entry_default, macro_veto_default

    verdict = str(state.get("verdict") or "")
    mss = _optional_float(state.get("mss_final"))
    cash = _optional_float(state.get("cash_ratio"))
    veto = macro_veto_default(settings)
    aggressive = aggressive_entry_default(settings)

    defensive = (
        verdict in cfg["defensive_verdicts"]
        or state.get("blocked") is True
        or state.get("audit_passed") is False
        or state.get("gate_passed") is False
        or (mss is not None and mss <= veto + cfg["weak_mss_below_veto_buffer"])
        or (verdict in _WATCH_VERDICTS and cash is not None and cash >= cfg["high_cash_ratio"])
    )
    if defensive:
        return "defensive"

    supportive = verdict in cfg["supportive_verdicts"]
    if mss is not None:
        supportive = supportive and mss >= aggressive + cfg["supportive_mss_above_aggressive"]
    if supportive:
        return "supportive"
    return "neutral"


def build_am_open_overlay_payload(
    *,
    mss_final: Optional[float] = None,
    verdict: Optional[str] = None,
    blocked: Optional[bool] = None,
    cash_ratio: Optional[float] = None,
    macro_summary: Optional[str] = None,
    audit_passed: Optional[bool] = None,
    gate_passed: Optional[bool] = None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    cfg = am_open_cfg(settings)
    state = compute_morning_open_state(
        mss_final=mss_final,
        verdict=verdict,
        blocked=blocked,
        cash_ratio=cash_ratio,
        macro_summary=macro_summary,
        audit_passed=audit_passed,
        gate_passed=gate_passed,
    )
    regime = classify_am_open_regime(state, cfg, settings=settings)
    return {
        "morning_date": today_shanghai().isoformat(),
        "regime": regime,
        "morning_state": state,
        "enabled": cfg["enabled"],
    }


def build_am_open_overlay_from_run(
    run_result: dict[str, Any],
    *,
    settings: dict[str, Any],
) -> dict[str, Any]:
    evaluation = run_result.get("evaluation") or {}
    report = evaluation.get("report") or {}
    snapshot = run_result.get("snapshot") or {}
    audit = evaluation.get("audit")
    gate = evaluation.get("gate")
    pf = snapshot.get("portfolio") or {}
    return build_am_open_overlay_payload(
        mss_final=_optional_float(report.get("mss_final")),
        verdict=str(report.get("verdict") or ""),
        blocked=bool(report.get("blocked")) if report.get("blocked") is not None else None,
        cash_ratio=_optional_float(pf.get("cash_ratio")),
        macro_summary=str(snapshot.get("macro_summary") or ""),
        audit_passed=getattr(audit, "passed", None),
        gate_passed=getattr(gate, "passed", None),
        settings=settings,
    )


def build_am_open_overlay_from_ctx(ctx: Any, *, settings: dict[str, Any]) -> dict[str, Any]:
    rows = list(getattr(ctx, "symbol_rows", None) or [])
    mss_vals: list[float] = []
    verdicts: list[str] = []
    for row in rows:
        report = getattr(row, "report", None) or {}
        if not isinstance(report, dict):
            continue
        mss = _optional_float(report.get("mss_final"))
        if mss is not None:
            mss_vals.append(mss)
        verdicts.append(str(report.get("verdict") or ""))
    primary = dict(getattr(ctx, "primary_snapshot", None) or {})
    if not primary and rows:
        snap = getattr(rows[0], "snapshot", None) or {}
        primary = dict(snap) if isinstance(snap, dict) else {}
    pf = primary.get("portfolio") or getattr(ctx, "portfolio", None) or {}
    return build_am_open_overlay_payload(
        mss_final=min(mss_vals) if mss_vals else None,
        verdict=_worst_verdict(verdicts),
        cash_ratio=_optional_float(pf.get("cash_ratio")),
        macro_summary=str(primary.get("macro_summary") or ""),
        settings=settings,
    )


def merge_am_open_into_handoff(overlay: dict[str, Any]) -> None:
    """Ensure today's morning handoff carries am_open_overlay (legacy/non-card path)."""
    from agent_reach.daily_run.close_morning_handoff import load_morning_handoff, save_morning_handoff

    day = today_shanghai()
    existing = load_morning_handoff(morning_day=day) or {}
    payload = {
        **existing,
        "morning_date": day.isoformat(),
        "am_open_overlay": dict(overlay),
    }
    payload.setdefault("action_checklist", [])
    save_morning_handoff(payload)


def load_am_open_overlay(*, morning_day: Optional[date] = None) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.close_morning_handoff import load_morning_handoff

    handoff = load_morning_handoff(morning_day=morning_day or today_shanghai())
    if not handoff:
        return None
    block = handoff.get("am_open_overlay")
    return dict(block) if isinstance(block, dict) else None


def _morning_scan_fallback(scans: list[dict[str, Any]]) -> dict[str, Any]:
    morning = [s for s in scans or [] if str(s.get("source") or "") == "morning"]
    if not morning:
        morning = [s for s in scans or [] if str(s.get("scan_id") or "").upper() in {"S1", "S2"}]
    if not morning:
        return {}
    last = morning[-1]
    return {
        "mss_final": _optional_float(last.get("mss_final")),
        "verdict": str(last.get("verdict") or "").strip() or None,
        "blocked": None,
        "cash_ratio": None,
        "macro_summary_present": False,
        "audit_passed": last.get("audit_passed"),
        "gate_passed": None,
    }


def _merge_prior_close_regime(regime: str, settings: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]]]:
    from agent_reach.daily_run.quant_calibration import load_prior_close_session_seed, merge_session_regime

    seed = load_prior_close_session_seed(settings=settings)
    if not seed:
        return regime, None
    seed_regime = str(seed.get("regime") or "").strip() or None
    return merge_session_regime(regime, seed_regime), seed


def apply_am_open_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
    *,
    dt=None,
) -> dict[str, Any]:
    """Backward-compatible alias; unified patching lives in session_overlay."""
    from agent_reach.daily_run.session_overlay import apply_session_overlay

    return apply_session_overlay(settings, scans, dt=dt)
