# -*- coding: utf-8
"""Industry funnel outcomes → weekly harness self-evolution."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement


def industry_funnel_to_harness_evidence(
    funnel: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []

    selected = list(funnel.get("selected") or [])
    codes = funnel.get("codes") or []
    memory.append(
        f"industry-funnel 周六精选 {len(selected)}/{funnel.get('candidates_scored', 0)} "
        f"→ 目标 {funnel.get('target', '?')}"
    )
    for row in selected[:5]:
        name = row.get("name") or row.get("code")
        code = row.get("code") or ""
        playbook.append(f"funnel 终选 {name}({code})")
    if len(selected) < int(funnel.get("target") or 0):
        plan.append("industry-funnel：候选不足，放宽 hot_topic 或 quality-screen 豁免")
        policy.append("industry-funnel：候选池偏窄，下月 funnel_target 维持或略降 quality 门槛")

    return {
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "summary": f"industry_funnel selected={len(codes)}",
    }


def run_weekly_industry_funnel(
    settings: dict[str, Any],
    *,
    enriched: dict[str, dict[str, Any]] | None = None,
    hot_titles: list[str] | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg, berkshire_enabled
    from agent_reach.daily_run.berkshire.industry_funnel import funnel_select_watchlist

    if not berkshire_enabled(settings):
        return {"skipped": True, "reason": "berkshire disabled"}
    bcfg = berkshire_cfg(settings)
    weekly = bcfg.get("industry_funnel_on_weekly")
    if weekly is None:
        weekly = bcfg.get("industry_funnel_on_close", True)
    if weekly is False:
        return {"skipped": True, "reason": "industry_funnel weekly disabled"}
    return funnel_select_watchlist(settings, enriched=enriched, hot_titles=hot_titles)


def apply_industry_funnel_harness_refinement(
    *,
    settings: Optional[dict[str, Any]] = None,
    enriched: dict[str, dict[str, Any]] | None = None,
    hot_titles: list[str] | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    harness_cfg = (cfg.get("harness") or {})
    if harness_cfg.get("enabled") is False:
        return {"skipped": True, "reason": "harness disabled", "job": "industry_funnel"}
    jobs = harness_cfg.get("jobs") or {}
    if isinstance(jobs, dict) and jobs.get("industry_funnel") is False:
        return {"skipped": True, "reason": "job industry_funnel disabled", "job": "industry_funnel"}

    funnel = run_weekly_industry_funnel(cfg, enriched=enriched, hot_titles=hot_titles)
    if funnel.get("skipped"):
        return {"skipped": True, "reason": funnel.get("reason"), "job": "industry_funnel"}
    evidence = industry_funnel_to_harness_evidence(funnel, settings=cfg)
    result = apply_skill_refinement("industry_funnel", evidence, settings=cfg)
    result["funnel"] = funnel
    return result
