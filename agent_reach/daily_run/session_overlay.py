# -*- coding: utf-8
"""Unified session overlay: merge regimes once, patch thresholds once, symbol gates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.pm_session_overlay import (
    _patch_threshold,
    _patch_trade_every_n,
    classify_pm_regime,
    compute_am_session_state,
    load_pm_session_overlay,
    pm_session_cfg,
)
from agent_reach.daily_run.week_open_overlay import load_week_open_overlay, week_open_cfg
from agent_reach.daily_run.am_open_overlay import load_am_open_overlay
from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import is_afternoon_session, is_morning_session, today_shanghai


@dataclass
class SessionOverlayContext:
    merged_regime: str = "neutral"
    session: str = "none"
    week_open_regime: Optional[str] = None
    seed_regime: Optional[str] = None
    session_regime: Optional[str] = None
    forecast_accuracy_defensive: bool = False
    symbol_gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    am_state: dict[str, Any] = field(default_factory=dict)
    am_open_source: str = ""
    pm_source: str = ""


def _merge_regimes(*regimes: Optional[str]) -> str:
    from agent_reach.daily_run.quant_calibration import merge_session_regime

    out = "neutral"
    for regime in regimes:
        if not regime:
            continue
        out = merge_session_regime(out, str(regime).strip())
    return out


def build_symbol_gates(
    operation_plans: list[dict[str, Any]],
    *,
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Per-symbol buy blocks from Sunday operation_plans."""
    gates: dict[str, dict[str, Any]] = {}
    for plan in operation_plans or []:
        code = _normalize_code(str(plan.get("code") or ""))
        if not code:
            continue
        text = str(plan.get("operation_plan") or plan.get("action") or "")
        gate = gates.setdefault(
            code,
            {"block_buy": False, "block_sell": False, "reasons": []},
        )
        if any(k in text for k in cfg.get("defensive_plan_keywords") or ()):
            gate["block_buy"] = True
            gate["reasons"].append(f"周日计划：{text[:48]}")
        if any(k in text for k in ("止损", "清仓")):
            gate["block_buy"] = True
            if "止损" in text:
                gate["reasons"].append("周日计划含止损，禁止抄底买入")
    for code, gate in gates.items():
        gate["reasons"] = list(dict.fromkeys(gate["reasons"]))[:3]
        _ = code
    return gates


def week_open_trade_block(
    settings: dict[str, Any],
    code: str,
    action: str,
) -> Optional[str]:
    """Return block reason when Sunday operation_plan blocks this symbol action."""
    runtime = settings.get("harness_runtime") or {}
    block = runtime.get("week_open") or {}
    if not block.get("active"):
        return None
    gates = block.get("symbol_gates") or {}
    row = gates.get(_normalize_code(code)) or {}
    action_l = str(action or "").lower()
    if action_l == "buy" and row.get("block_buy"):
        reasons = row.get("reasons") or ["周日 operation_plan 阻断买入"]
        return str(reasons[0])
    return None


def _forecast_symbol_accuracy_defensive(settings: dict[str, Any]) -> tuple[bool, str]:
    wf_cfg = dict((settings or {}).get("week_forecast") or {})
    if wf_cfg.get("pm_session_symbol_accuracy_gate", True) is False:
        return False, ""
    threshold = float(wf_cfg.get("pm_session_symbol_accuracy_min", 0.45))
    from agent_reach.daily_run.week_forecast import load_active_forecast

    forecast = load_active_forecast()
    if not forecast:
        return False, ""
    last = forecast.get("last_review") or {}
    acc = last.get("accuracy")
    if acc is None:
        actuals = forecast.get("actuals") or {}
        hits = 0
        total = 0
        for row in actuals.values():
            if not isinstance(row, dict):
                continue
            for sym in (row.get("symbols") or {}).values():
                if not isinstance(sym, dict):
                    continue
                if sym.get("hit") is not None:
                    total += 1
                    if sym.get("hit"):
                        hits += 1
        if total:
            acc = hits / total
    if acc is None:
        return False, ""
    if float(acc) < threshold:
        return True, f"当周预测符号命中率 {float(acc):.0%} 低于 {threshold:.0%}"
    return False, ""


def _compute_am_open_regime(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], str]:
    from agent_reach.daily_run.am_open_overlay import (
        am_open_cfg,
        classify_am_open_regime,
        _morning_scan_fallback,
    )

    cfg = am_open_cfg(settings)
    saved = load_am_open_overlay()
    if saved and saved.get("enabled") is False:
        return "neutral", {}, ""
    if saved and isinstance(saved.get("morning_state"), dict):
        state = dict(saved["morning_state"])
        regime = str(saved.get("regime") or classify_am_open_regime(state, cfg, settings=settings))
        return regime, state, "morning_handoff"
    state = _morning_scan_fallback(scans)
    if not state:
        return "neutral", {}, ""
    return classify_am_open_regime(state, cfg, settings=settings), state, "intraday_fallback"


def compute_session_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
    *,
    dt=None,
) -> SessionOverlayContext:
    from agent_reach.daily_run.quant_calibration import load_prior_close_session_seed

    ctx = SessionOverlayContext()
    morning = is_morning_session(dt)
    afternoon = is_afternoon_session(dt)
    if morning:
        ctx.session = "morning"
    elif afternoon:
        ctx.session = "afternoon"

    seed = load_prior_close_session_seed(settings=settings)
    if seed:
        ctx.seed_regime = str(seed.get("regime") or "").strip() or None

    wo_cfg = week_open_cfg(settings)
    week_open = load_week_open_overlay()
    if week_open and week_open.get("enabled") is not False:
        ws = str(week_open.get("week_start") or "")
        we = str(week_open.get("week_end") or "")
        today = today_shanghai()
        in_week = True
        if ws and we:
            try:
                from datetime import date

                in_week = date.fromisoformat(ws) <= today <= date.fromisoformat(we)
            except ValueError:
                in_week = True
        if in_week:
            ctx.week_open_regime = str(week_open.get("regime") or "").strip() or None
            ctx.symbol_gates = build_symbol_gates(
                list(week_open.get("operation_plans") or []),
                cfg=wo_cfg,
            )
            ctx.reasons.extend(list(week_open.get("reasons") or [])[:2])

    if morning:
        regime, state, source = _compute_am_open_regime(settings, scans)
        ctx.session_regime = regime
        ctx.am_state = state
        ctx.am_open_source = source
    elif afternoon:
        pm_cfg = pm_session_cfg(settings)
        saved = load_pm_session_overlay()
        if saved and saved.get("enabled") is False:
            am_state: dict[str, Any] = {}
            regime = "neutral"
            source = ""
        elif saved and isinstance(saved.get("am_state"), dict):
            am_state = dict(saved["am_state"])
            regime = str(saved.get("regime") or classify_pm_regime(am_state, pm_cfg))
            source = "midday_handoff"
        else:
            am_state = compute_am_session_state(scans, settings=settings)
            regime = classify_pm_regime(am_state, pm_cfg)
            source = "intraday_fallback"
        ctx.am_state = am_state
        ctx.session_regime = regime
        ctx.pm_source = source
        acc_def, acc_reason = _forecast_symbol_accuracy_defensive(settings)
        ctx.forecast_accuracy_defensive = acc_def
        if acc_def and acc_reason:
            ctx.reasons.append(acc_reason)

    regimes = [ctx.week_open_regime, ctx.seed_regime, ctx.session_regime]
    if ctx.forecast_accuracy_defensive:
        regimes.append("defensive")
    ctx.merged_regime = _merge_regimes(*regimes)
    return ctx


def apply_session_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
    *,
    dt=None,
) -> dict[str, Any]:
    """Merge week_open + close seed + am/pm session; patch thresholds once."""
    ctx = compute_session_overlay(settings, scans, dt=dt)
    if ctx.session == "none":
        return settings

    out = deepcopy(settings)
    runtime = dict(out.get("harness_runtime") or {})

    if ctx.week_open_regime or ctx.symbol_gates:
        runtime["week_open"] = {
            "active": True,
            "regime": ctx.week_open_regime or "neutral",
            "symbol_gates": ctx.symbol_gates,
            "source": "forecast_operation_plans",
        }

    if ctx.seed_regime:
        runtime["session_seed"] = {
            "seed_regime": ctx.seed_regime,
            "merged_regime": ctx.merged_regime,
        }

    if ctx.session == "morning" and ctx.am_open_source:
        runtime["am_open"] = {
            "active": ctx.merged_regime != "neutral",
            "regime": ctx.merged_regime,
            **ctx.am_state,
            "source": ctx.am_open_source,
            "merged": True,
        }
    elif ctx.session == "afternoon" and ctx.pm_source:
        runtime["pm_session"] = {
            "active": ctx.merged_regime != "neutral",
            "regime": ctx.merged_regime,
            **ctx.am_state,
            "source": ctx.pm_source,
            "merged": True,
            "forecast_accuracy_defensive": ctx.forecast_accuracy_defensive,
        }

    if ctx.merged_regime == "neutral":
        out["harness_runtime"] = runtime
        _record_overlay_telemetry(out, ctx)
        return out

    from agent_reach.daily_run.quant_calibration import effective_overlay_deltas

    block_name = "morning_open" if ctx.session == "morning" else "pm_session"
    deltas = effective_overlay_deltas(block_name, settings)
    wo_cfg = dict((settings or {}).get("week_open") or {})
    if ctx.week_open_regime == "defensive":
        deltas = {
            **deltas,
            "aggressive_entry_delta": max(
                float(deltas.get("aggressive_entry_delta", 0)),
                float(wo_cfg.get("aggressive_entry_delta", 1.5)),
            ),
            "macro_veto_delta": max(
                float(deltas.get("macro_veto_delta", 0)),
                float(wo_cfg.get("macro_veto_delta", 1.5)),
            ),
        }

    from agent_reach.daily_run.harness_policy import aggressive_entry_default, macro_veto_default

    if ctx.merged_regime == "defensive":
        _patch_threshold(
            out,
            key="aggressive_entry",
            effective=aggressive_entry_default(settings) + float(deltas["aggressive_entry_delta"]),
            source="session_overlay",
        )
        _patch_threshold(
            out,
            key="macro_veto",
            effective=macro_veto_default(settings) + float(deltas["macro_veto_delta"]),
            source="session_overlay",
        )
        if int(deltas.get("trade_every_n_delta") or 0):
            _patch_trade_every_n(
                out,
                delta=int(deltas["trade_every_n_delta"]),
                source="session_overlay",
            )
    elif ctx.merged_regime == "supportive":
        base_agg = aggressive_entry_default(settings)
        effective = max(
            macro_veto_default(settings) + 2.0,
            base_agg + float(deltas.get("supportive_aggressive_entry_delta", -1.0)),
        )
        _patch_threshold(out, key="aggressive_entry", effective=effective, source="session_overlay")
        sup_n = int(deltas.get("supportive_trade_every_n_delta") or 0)
        if sup_n:
            _patch_trade_every_n(out, delta=sup_n, source="session_overlay")

    out["harness_runtime"] = runtime
    _record_overlay_telemetry(out, ctx)
    return out


def _record_overlay_telemetry(settings: dict[str, Any], ctx: SessionOverlayContext) -> None:
    try:
        from agent_reach.daily_run.overlay_telemetry import record_session_overlay

        record_session_overlay(settings, ctx)
    except Exception:
        pass


def aggregate_week_overlay_stats(
    week_start: date,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.overlay_telemetry import aggregate_week_overlay_stats as _agg

    return _agg(week_start, week_end, settings=settings)
