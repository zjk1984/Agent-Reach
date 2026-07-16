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
