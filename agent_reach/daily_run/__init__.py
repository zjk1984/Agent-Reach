# -*- coding: utf-8 -*-
"""Daily run skill — data audit, verdict, quality gate, report pipeline."""

from agent_reach.daily_run.auditor import AuditResult, run_data_audit
from agent_reach.daily_run.pipeline import build_report, evaluate_snapshot, push_report
from agent_reach.daily_run.quality_gate import GateResult, validate_report
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.verdict import VerdictResult, compute_verdict

__all__ = [
    "AuditResult",
    "GateResult",
    "VerdictResult",
    "build_report",
    "compute_verdict",
    "evaluate_snapshot",
    "load_settings",
    "push_report",
    "run_data_audit",
    "validate_report",
]
