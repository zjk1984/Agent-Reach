# -*- coding: utf-8
"""Shared pytest fixtures for Agent Reach tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_daily_run_state(monkeypatch, tmp_path):
    """Keep schedule/integration tests from writing to ~/.agent-reach/daily_run."""
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("agent_reach.daily_run.run_manifest.runs_dir", lambda: runs)
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_builder.default_portfolio_path",
        lambda: portfolio_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_cache.last_snapshot_path",
        lambda: tmp_path / "last_snapshot.json",
    )

    # Harness self-evolution state (memory/policy/playbook/plan, refinements,
    # apply-audit trail, runtime overlay diffs) must never touch the real
    # ~/.agent-reach/daily_run/harness — this machine also runs live daily-run
    # cron jobs concurrently with the test suite, and several tests were
    # silently reading real accumulated harness state instead of a clean
    # baseline (e.g. real evolved pnl_target.base_target_pct leaking into
    # test_compute_target_from_pct; real policy/plan text leaking into
    # test_intraday_narrative_includes_context_trace's context_trace assertion).
    #
    # harness.py's _state_path()/_refinements_path()/harness_dir() and
    # harness_apply_gate.py's _audit_path() all do a fresh
    # ``from agent_reach.daily_run.harness_git import ...`` *inside* their
    # function bodies, so patching these two harness_git functions here is
    # enough to redirect every consumer — no per-test-file fixture needed.
    # (Tests that assert on resolve_harness_paths' own branch-aware behavior
    # import it directly at module scope and are unaffected by this patch.)
    harness_root = tmp_path / "harness"
    harness_root.mkdir(parents=True, exist_ok=True)
    harness_paths = {
        "root": harness_root,
        "branch": "test",
        "state": harness_root / "harness_state.json",
        "refinements": harness_root / "refinements.jsonl",
        "snapshots": harness_root / "snapshots",
        "registry": harness_root / "study_registry.json",
        "audit": harness_root / "apply_audit.jsonl",
    }
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_git.resolve_harness_paths",
        lambda settings=None: dict(harness_paths),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_git.resolve_harness_state_path",
        lambda settings=None: harness_paths["state"],
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_git._harness_root",
        lambda: harness_root,
    )

    # Trade ledger / daily trade-count state: same real-file leak as harness
    # state above (e.g. pnl_buy_block_reason() replaying the real, live
    # ~/.agent-reach/daily_run/trade_ledger.jsonl caused non-deterministic
    # "连亏警戒" buy blocks in portfolio_manager tests depending on what the
    # concurrently-running cron jobs had traded that day). default_ledger_path
    # is imported directly (frozen reference) by realized_pnl.py and
    # weekly_report.py, so each needs its own patch in addition to the
    # defining module.
    ledger_path = tmp_path / "trade_ledger.jsonl"
    monkeypatch.setattr("agent_reach.daily_run.portfolio_manager.default_ledger_path", lambda: ledger_path)
    monkeypatch.setattr("agent_reach.daily_run.realized_pnl.default_ledger_path", lambda: ledger_path)
    monkeypatch.setattr("agent_reach.daily_run.weekly_report.default_ledger_path", lambda: ledger_path)
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.daily_trade_state_path",
        lambda: tmp_path / "daily_trade_state.json",
    )

    # is_continuous_session() gates should_evaluate_trade() on real wall-clock
    # time (A-share continuous trading hours), which would otherwise make the
    # whole suite flaky/order-dependent depending on when tests happen to run.
    # Default to "always in session" so existing tests stay deterministic;
    # tests that specifically exercise the session gate monkeypatch this back.
    # intraday.py does ``from trade_calendar import is_continuous_session`` (a
    # frozen name binding), so both the defining module and that import site
    # need patching.
    monkeypatch.setattr("agent_reach.daily_run.trade_calendar.is_continuous_session", lambda dt=None: True)
    monkeypatch.setattr("agent_reach.daily_run.intraday.is_continuous_session", lambda dt=None: True)

    # Morning baseline / capital events / daily P&L history: same real-file leak
    # as harness state and the trade ledger above. This machine also runs the
    # live daily-run cron, so ~/.agent-reach/daily_run/last_morning.json,
    # capital_events.jsonl, and pnl_history.jsonl all have real, non-empty
    # content that would otherwise silently feed close_code_review's
    # cash-vs-ledger check / pnl-history-gap check during tests.
    monkeypatch.setattr(
        "agent_reach.daily_run.workflows._default_baseline_path",
        lambda: tmp_path / "last_morning.json",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.capital_events.default_capital_events_path",
        lambda: tmp_path / "capital_events.jsonl",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.daily_pnl_history.default_pnl_history_path",
        lambda: tmp_path / "pnl_history.jsonl",
    )
