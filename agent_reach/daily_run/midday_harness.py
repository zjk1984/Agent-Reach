# -*- coding: utf-8
"""Midday (12:30) macro-refresh / Lookback findings → harness self-evolution.

Mirrors intraday_harness.py's lightweight, followup-only pattern: midday is a
light-touch check-in (not a decision gate), so harness evidence is collected
after the main card is pushed rather than embedded in it.
"""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement


def midday_to_harness_evidence(run_result: dict[str, Any]) -> dict[str, Any]:
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []

    if run_result.get("skipped"):
        reason = str(run_result.get("message") or run_result.get("reason") or "")
        return {
            "memory": [f"midday skipped：{reason}"] if reason else [],
            "policy": [],
            "playbook": [],
            "plan": [],
            "summary": f"midday skipped: {reason}",
        }

    scan_result = run_result.get("scan_result") or {}
    scan = run_result.get("scan") or scan_result.get("scan") or {}
    evaluation = run_result.get("evaluation") or {}
    scan_id = scan.get("scan_id") or "midday"
    name = scan.get("name") or scan.get("code") or "标的"
    mss = scan.get("mss_final")
    verdict = scan.get("verdict")
    trend = scan_result.get("trend") or "flat"
    lookback_mss = scan_result.get("lookback_mss")

    if mss is not None:
        memory.append(f"午盘 {scan_id} {name} MSS={mss} verdict={verdict or '—'} trend={trend}")

    audit = evaluation.get("audit")
    audit_passed = getattr(audit, "passed", None)
    if audit_passed is False:
        issues = "；".join(getattr(audit, "issues", None) or [])
        memory.append(f"午盘数据审计未通过：{issues or '未知原因'}")
        policy.append("午盘审计未通过：检查行情/宏观数据源覆盖率（midday 目前不拦截推送，仅告警）")

    baseline_mss = None
    try:
        from agent_reach.daily_run.workflows import load_morning_baseline

        baseline = load_morning_baseline()
        baseline_mss = (baseline or {}).get("mss_final") or ((baseline or {}).get("report") or {}).get(
            "mss_final"
        )
    except Exception:
        baseline_mss = None

    if baseline_mss is not None and mss is not None:
        try:
            delta = float(mss) - float(baseline_mss)
        except (TypeError, ValueError):
            delta = 0.0
        if abs(delta) >= 15:
            direction = "大幅走强" if delta > 0 else "大幅走弱"
            memory.append(
                f"午盘较早盘基线{direction}：早盘 {baseline_mss} → 午盘 {mss}（Δ{delta:+.1f}）"
            )
            plan.append(f"intraday：{name} 午后关注 MSS 是否延续午盘方向，避免早盘惯性判断")

    if trend in ("turning_up", "turning_down") and lookback_mss is not None:
        playbook.append(f"午盘 Lookback 拐点 {trend}（{lookback_mss:.1f} 分），午后重点验证 S_n+1")

    xueqiu_cross = scan_result.get("xueqiu_cross") or {}
    if isinstance(xueqiu_cross, dict) and xueqiu_cross.get("alerts"):
        memory.append(f"午盘雪球热度交叉告警 {len(xueqiu_cross['alerts'])} 条")

    enriched = scan_result.get("enriched") or {}
    if not str(enriched.get("macro_summary") or "").strip():
        memory.append("午盘宏观刷新未获取摘要：检查网络 / 60s / 雪球 Cookie")
        plan.append("midday：确认 macro_refresh 数据源可用性")

    summary = f"midday {scan_id} {name} mss={mss} trend={trend}"
    return {
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "summary": summary,
    }


def apply_midday_harness_refinement(
    run_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    evidence = midday_to_harness_evidence(run_result)
    if not any(evidence.get(k) for k in ("memory", "policy", "playbook", "plan")):
        return {"skipped": True, "reason": "empty evidence", "job": "midday"}
    return apply_skill_refinement("midday", evidence, settings=settings)
