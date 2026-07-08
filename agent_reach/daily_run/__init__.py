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
from agent_reach.daily_run.intraday import (
    evaluate_trade,
    load_state as load_intraday_state,
    record_scan,
    reset_state as reset_intraday_state,
    run_intraday,
)
from agent_reach.daily_run.lookback import compute_lookback_mss, detect_mss_trend
from agent_reach.daily_run.workflows import load_morning_baseline, run_close, run_morning, save_morning_baseline

__all__ = [
    "AuditResult",
    "BacktestResult",
    "GateResult",
    "OptimizeResult",
    "VerdictResult",
    "VerifyResult",
    "build_report",
    "compute_lookback_mss",
    "compute_verdict",
    "detect_mss_trend",
    "evaluate_snapshot",
    "evaluate_trade",
    "grid_search_optimize",
    "list_plugins",
    "load_intraday_state",
    "load_morning_baseline",
    "load_settings",
    "push_report",
    "record_scan",
    "reset_intraday_state",
    "run_close",
    "run_data_audit",
    "run_intraday",
    "run_experts",
    "run_morning",
    "run_mss_backtest",
    "save_morning_baseline",
    "save_optimized_settings",
    "validate_report",
    "verify_snapshots",
]
