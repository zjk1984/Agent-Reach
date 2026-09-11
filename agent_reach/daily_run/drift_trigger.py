# -*- coding: utf-8
"""Drift trigger — MSS / forecast / thesis deviation gates (Qlib concept-drift inspired)."""

from __future__ import annotations

from typing import Any, Optional


def drift_trigger_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("drift_trigger") or {})
    actions = block.get("actions") or ["alert", "harness_only"]
    if isinstance(actions, str):
        actions = [a.strip() for a in actions.split(",") if a.strip()]
    return {
        "enabled": block.get("enabled", True) is not False,
        "mss_drift_pts": float(block.get("mss_drift_pts", 3.0)),
        "weekly_pnl_alert_pct": float(block.get("weekly_pnl_alert_pct", -2.0)),
        "forecast_miss_pts": float(block.get("forecast_miss_pts", 4.0)),
        "thesis_drift_score_min": float(block.get("thesis_drift_score_min", 2.0)),
        "actions": tuple(str(a) for a in actions),
        "block_trade_on_trigger": block.get("block_trade_on_trigger", False) is True,
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_drift(
    *,
    report: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = drift_trigger_cfg(settings)
    if not cfg["enabled"]:
        return {"triggered": False, "skipped": True, "reasons": [], "actions": []}

    report = report or {}
    snapshot = snapshot or {}
    reasons: list[str] = []

    weekly_pct = _optional_float(report.get("weekly_pnl_pct"))
    if weekly_pct is not None and weekly_pct <= cfg["weekly_pnl_alert_pct"]:
        reasons.append(f"weekly_pnl {weekly_pct:+.2f}% ≤ 阈值 {cfg['weekly_pnl_alert_pct']:.1f}%")

    mss_now = _optional_float(snapshot.get("mss_final") or report.get("mss_final"))
    mss_plan = _optional_float(report.get("planned_mss") or report.get("target_mss"))
    if mss_now is not None and mss_plan is not None:
        delta = abs(mss_now - mss_plan)
        if delta >= cfg["mss_drift_pts"]:
            reasons.append(f"MSS 偏离计划 {delta:.1f}pt ≥ {cfg['mss_drift_pts']:.1f}")

    forecast_miss = _optional_float(report.get("forecast_miss_pts") or report.get("forecast_tracking_miss"))
    if forecast_miss is not None and forecast_miss >= cfg["forecast_miss_pts"]:
        reasons.append(f"forecast miss {forecast_miss:.1f}pt ≥ {cfg['forecast_miss_pts']:.1f}")

    thesis_score = _optional_float(report.get("thesis_drift_score"))
    if thesis_score is not None and thesis_score >= cfg["thesis_drift_score_min"]:
        reasons.append(f"thesis drift score {thesis_score:.1f} ≥ {cfg['thesis_drift_score_min']:.1f}")

    triggered = bool(reasons)
    actions = list(cfg["actions"]) if triggered else []
    if triggered and cfg["block_trade_on_trigger"] and "block_trade" not in actions:
        actions.append("block_trade")

    return {
        "triggered": triggered,
        "skipped": False,
        "reasons": reasons,
        "actions": actions,
        "config": {
            "mss_drift_pts": cfg["mss_drift_pts"],
            "weekly_pnl_alert_pct": cfg["weekly_pnl_alert_pct"],
        },
    }


def drift_trade_block_reason(
    *,
    report: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    drift = evaluate_drift(report=report, snapshot=snapshot, settings=settings)
    if not drift.get("triggered"):
        return None
    if "block_trade" not in (drift.get("actions") or []):
        return None
    first = (drift.get("reasons") or ["drift triggered"])[0]
    return f"drift_trigger：{first}"


def drift_trigger_to_harness_evidence(drift: dict[str, Any]) -> dict[str, Any]:
    if drift.get("skipped") or not drift.get("triggered"):
        return {"summary": "drift_trigger ok", "memory": [], "policy": [], "playbook": [], "plan": []}
    reasons = drift.get("reasons") or []
    return {
        "summary": f"drift_trigger: {'; '.join(reasons[:2])}",
        "memory": [f"drift: {r}" for r in reasons[:3]],
        "policy": [f"drift_guard weekly_pnl_alert={drift.get('config', {}).get('weekly_pnl_alert_pct')}"],
        "playbook": ["drift 触发时优先跑 hyperopt-lite / sell_rules_whatif，暂缓加仓"],
        "plan": ["下周验证 drift 动作是否降低 MSS/forecast 偏离"],
        "rigor_domain": {"drift_trigger": drift},
    }


def render_drift_trigger_markdown(drift: dict[str, Any]) -> str:
    if drift.get("skipped"):
        return "## Drift Trigger\n\n已跳过。"
    if not drift.get("triggered"):
        return "## ✅ Drift Trigger\n\n未检测到显著漂移。"
    lines = ["## ⚠️ Drift Trigger", ""]
    for reason in drift.get("reasons") or []:
        lines.append(f"- {reason}")
    if drift.get("actions"):
        lines.append(f"- 建议动作：**{', '.join(drift['actions'])}**")
    return "\n".join(lines)
