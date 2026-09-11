# -*- coding: utf-8
"""Weekly hyperopt-lite harness refinement."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement
from agent_reach.daily_run.hyperopt_lite import hyperopt_lite_to_harness_evidence, run_hyperopt_lite


def apply_hyperopt_lite_harness_refinement(
    report: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    result = run_hyperopt_lite(report, settings=settings)
    if result.get("skipped"):
        return result
    try:
        from agent_reach.daily_run.experiment_recorder import record_hyperopt_experiment

        record_hyperopt_experiment(result, settings=settings)
    except Exception:
        pass
    evidence = hyperopt_lite_to_harness_evidence(result, report=report)
    refine = apply_skill_refinement("hyperopt_lite", evidence, settings=settings)
    return {**result, **refine}
