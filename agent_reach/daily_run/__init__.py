# -*- coding: utf-8
"""Daily run skill — data audit, verdict, quality gate, report pipeline."""

from agent_reach.daily_run.auditor import AuditResult, run_data_audit
from agent_reach.daily_run.backtest import BacktestResult, run_mss_backtest
from agent_reach.daily_run.optimizer import OptimizeResult, grid_search_optimize, save_optimized_settings
from agent_reach.daily_run.pipeline import build_report, evaluate_snapshot, push_report
from agent_reach.daily_run.plugins.loader import list_plugins, run_experts
from agent_reach.daily_run.quality_gate import GateResult, validate_report
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.verdict import VerdictResult, compute_verdict
from agent_reach.daily_run.verify import VerifyResult, verify_snapshots

__all__ = [
    "AuditResult",
    "BacktestResult",
    "GateResult",
    "OptimizeResult",
    "VerdictResult",
    "VerifyResult",
    "build_report",
    "compute_verdict",
    "evaluate_snapshot",
    "grid_search_optimize",
    "list_plugins",
    "load_settings",
    "push_report",
    "run_data_audit",
    "run_experts",
    "run_mss_backtest",
    "save_optimized_settings",
    "validate_report",
    "verify_snapshots",
]
