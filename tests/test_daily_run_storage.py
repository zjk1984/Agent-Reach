# -*- coding: utf-8
"""Tests for daily-run SQLite storage (Phase 1–3 scaffolding)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_reach.daily_run.storage import get_store, reset_store, storage_enabled
from agent_reach.daily_run.storage.backfill import backfill_from_files
from agent_reach.daily_run.storage.distill import run_distill
from agent_reach.daily_run.storage.hooks import (
    on_experience_entry,
    on_harness_refinement,
    on_portfolio_save,
    on_trade_ledger,
)
from agent_reach.daily_run.storage.sqlite_store import SqliteDailyRunStore


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    db_path = tmp_path / "daily_run.db"
    root = tmp_path / "daily_run"
    root.mkdir()
    settings = {
        "storage": {
            "enabled": True,
            "backend": "sqlite",
            "sqlite_path": str(db_path),
            "distill": {"enabled": True, "auto_after_close": False},
        }
    }
    monkeypatch.setenv("AGENT_REACH_STORAGE", "1")
    monkeypatch.setattr(
        "agent_reach.daily_run.settings.load_settings",
        lambda path=None: settings,
    )
    reset_store()
    yield {"db_path": db_path, "root": root, "settings": settings}
    reset_store()


def test_sqlite_trade_and_portfolio_dual_write(storage_env):
    settings = storage_env["settings"]
    assert storage_enabled(settings)

    on_trade_ledger(
        {
            "at": "2026-08-25T08:00:00+00:00",
            "trade_id": "T1",
            "decision_action": "buy",
            "actions": [
                {
                    "side": "buy",
                    "code": "603986",
                    "name": "兆易创新",
                    "shares": 100,
                    "price": 120.5,
                    "amount": 12050.0,
                    "commission": 18.0,
                    "reasoning": "test buy",
                }
            ],
        }
    )
    on_portfolio_save(
        {
            "cash": 100000.0,
            "total": 112050.0,
            "holdings": [
                {"code": "603986", "name": "兆易创新", "shares": 100, "cost": 120.5},
            ],
        },
        source="test",
    )

    store = get_store(settings)
    status = store.status()
    assert status["counts"]["l0_events"] >= 2
    assert status["counts"]["positions"] == 1

    trades = store.query_trades(code="603986", limit=10)
    assert len(trades) == 1
    assert trades[0]["action"]["side"] == "buy"


def test_backfill_from_fixture_tree(storage_env):
    root = storage_env["root"]
    settings = storage_env["settings"]

    ledger = root / "trade_ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "at": "2026-08-25T09:00:00+00:00",
                "trade_id": "T2",
                "actions": [{"side": "sell", "code": "300308", "shares": 100, "price": 50.0}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "portfolio.json").write_text(
        json.dumps({"cash": 50000, "total": 50000, "holdings": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    exp_dir = root / "experience"
    exp_dir.mkdir()
    (exp_dir / "experience.jsonl").write_text(
        json.dumps(
            {
                "date": "2026-08-25",
                "at": "2026-08-25T10:00:00+00:00",
                "code": "300308",
                "verdict": "hold",
                "rules": [{"text": "avoid chase"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = backfill_from_files(root=root, settings=settings)
    assert result["backfilled"]["trade"] == 1
    assert result["backfilled"]["experience"] == 1

    store = get_store(settings)
    assert store.query_trades(code="300308")


def test_distill_l0_to_l1_atoms(storage_env):
    settings = storage_env["settings"]
    store = SqliteDailyRunStore(Path(storage_env["db_path"]))

    event_id = store.append_l0_event(
        "experience",
        {
            "at": "2026-08-25T10:00:00+00:00",
            "code": "300308",
            "name": "中际旭创",
            "verdict": "hold",
            "mss_final": 55.0,
            "rules": [{"text": "不追涨停"}],
        },
        dedupe_key="exp:1",
    )
    assert event_id > 0

    reset_store()
    result = run_distill(settings=settings, limit=50)
    assert result["processed_events"] >= 1
    assert result["atoms_created"] >= 1

    atoms = get_store(settings).query_l1_atoms(code="300308", limit=10)
    assert any(a["kind"] == "experience_rule" for a in atoms)


def test_harness_refinement_history(storage_env):
    settings = storage_env["settings"]
    on_harness_refinement(
        {
            "id": "refine_0001",
            "job": "close",
            "trigger": "test",
            "changes": ["policy/cash_guard updated"],
            "evidence": "defensive day",
            "created_at": "2026-08-25T11:00:00+00:00",
            "edits": [
                {
                    "action": "update",
                    "kind": "policy",
                    "entry_id": "cash_guard",
                    "before": {"content": "old"},
                    "after": {"content": "new"},
                }
            ],
        }
    )
    store = get_store(settings)
    status = store.status()
    assert status["counts"]["l0_events"] >= 1
    assert status["counts"]["harness_entry_history"] >= 1


def test_storage_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_REACH_STORAGE", raising=False)
    from agent_reach.daily_run.settings import load_settings

    settings = load_settings()
    assert storage_enabled(settings) is False
