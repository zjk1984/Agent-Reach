# -*- coding: utf-8
"""Weekly drift-trigger harness refinement."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.drift_trigger import drift_trigger_to_harness_evidence, evaluate_drift
from agent_reach.daily_run.harness_skill_base import apply_skill_refinement


def apply_drift_trigger_harness_refinement(
    report: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    drift = evaluate_drift(report=report, snapshot=snapshot, settings=settings)
    if drift.get("skipped") or not drift.get("triggered"):
        return {**drift, "skipped": True, "reason": "no drift trigger", "job": "drift_trigger"}
    evidence = drift_trigger_to_harness_evidence(drift)
    refine = apply_skill_refinement("drift_trigger", evidence, settings=settings)
    return {**drift, **refine, "job": "drift_trigger"}
