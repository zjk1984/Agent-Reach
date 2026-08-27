# -*- coding: utf-8
"""Weekly rejected refresh outcomes → harness weekly_whatif threshold evolution."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement, merge_harness_evidence
from agent_reach.daily_run.rejected_whatif_policy import (
    _WEEKLY_WHATIF_KEYS,
    format_weekly_whatif_policy_line,
    weekly_whatif_policy_base,
)
from agent_reach.daily_run.rejected_whatif_optimizer import optimize_weekly_whatif_with_deepseek


def _rejected_whatif_harness_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = settings or {}
    harness = cfg.get("harness") or {}
    if harness.get("enabled") is False:
        return False
    rejected_cfg = cfg.get("rejected_strategies") or {}
    if rejected_cfg.get("harness_evolve", True) is False:
        return False
    whatif_cfg = dict(rejected_cfg.get("weekly_whatif") or {})
    return whatif_cfg.get("mode", "harness") != "fixed"


def weekly_rejected_refresh_to_harness_evidence(
    report: dict[str, Any],
    *,
    refresh_result: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.skill_rejected import _candidates_from_weekly_report

    refresh = refresh_result or {}
    added = list(refresh.get("added") or [])
    archived = int(refresh.get("archived") or 0)
    pnl_pct = float(report.get("weekly_pnl_pct") or 0)
    candidates = _candidates_from_weekly_report(report, settings)

    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []

    memory.append(
        f"证伪库 weekly refresh：入库 {len(added)} 条，归档 {archived} 条，"
        f"候选 {len(candidates)} 条，周度 {pnl_pct:+.2f}%"
    )
    if added:
        memory.append("当周证伪：" + "、".join(str(t) for t in added[:4]))

    if pnl_pct >= 0 and added:
        policy.append("盈利周证伪库仍入库：收紧 weekly_whatif 阈值")
        plan.append("rejected_whatif：盈利周提高 auto-add 门槛，减少误杀")
    elif pnl_pct < -1.0 and not added and candidates:
        policy.append("亏损周证伪库漏检：适度放宽 weekly_whatif 阈值")
        plan.append("rejected_whatif：亏损周核对 what-if 信号是否被阈值挡掉")
    if len(added) >= 2:
        policy.append("证伪库当周入库偏多：收紧 macro/what-if 门槛")
    if any("宏观" in reason for _, reason in candidates) and len(candidates) == 1:
        policy.append("macro 需 what-if 佐证：维持 require_whatif_for_macro")

    current = weekly_whatif_policy_base(settings)
    policy_line = format_weekly_whatif_policy_line(
        current,
        rationale=f"weekly refresh added={len(added)} pnl={pnl_pct:+.2f}%",
    )
    if policy_line:
        playbook.append("weekly_whatif 阈值由 harness 自进化维护（rejected weekly_whatif最优 policy line）")

    summary = f"rejected_whatif added={len(added)} candidates={len(candidates)} pnl={pnl_pct:+.2f}%"
    return {
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "summary": summary,
        "rigor_domain": {
            "weekly_pnl_pct": pnl_pct,
            "added": added,
            "archived": archived,
            "candidate_count": len(candidates),
            "current_weekly_whatif": {k: current.get(k) for k in _WEEKLY_WHATIF_KEYS},
        },
    }


def apply_weekly_rejected_whatif_harness_refinement(
    report: dict[str, Any],
    *,
    refresh_result: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not _rejected_whatif_harness_enabled(settings):
        return {"skipped": True, "reason": "rejected weekly_whatif harness disabled", "job": "rejected_whatif"}

    evidence = weekly_rejected_refresh_to_harness_evidence(
        report,
        refresh_result=refresh_result,
        settings=settings,
    )
    llm_opt = optimize_weekly_whatif_with_deepseek(
        report,
        refresh_result=refresh_result,
        settings=settings,
    )
    if not llm_opt.get("skipped") and llm_opt.get("evidence"):
        evidence = merge_harness_evidence(evidence, llm_opt["evidence"])
        if isinstance(evidence.get("rigor_domain"), dict):
            evidence["rigor_domain"]["llm_optimal"] = llm_opt.get("optimal")

    result = apply_skill_refinement("rejected_whatif", evidence, settings=settings)
    if not llm_opt.get("skipped"):
        result["llm_optimize"] = {
            "skipped": False,
            "planner": llm_opt.get("planner"),
            "optimal": llm_opt.get("optimal"),
            "provider": llm_opt.get("provider"),
        }
    else:
        result["llm_optimize"] = {"skipped": True, "reason": llm_opt.get("reason")}
    return result
