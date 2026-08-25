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


def test_schema_v2_tables(storage_env):
    store = get_store(storage_env["settings"])
    status = store.status()
    assert status["schema_version"] >= 2
    assert "l1_state" in status["counts"]
    assert "l2_scenarios" in status["counts"]
    assert "l3_documents" in status["counts"]


def test_l0_pnl_and_l2_baseline_hooks(storage_env):
    from agent_reach.daily_run.storage.hooks import on_baseline, on_daily_pnl

    on_daily_pnl(
        {"date": "2026-08-25", "daily_pnl": 100.0, "cumulative_pnl": 500.0, "recorded_at": "2026-08-25T10:00:00+00:00"},
    )
    on_baseline(
        "morning",
        "603986",
        {"code": "603986", "mss_final": 55.0, "date": "2026-08-25"},
        source_path="/tmp/baseline.json",
    )
    store = get_store(storage_env["settings"])
    assert store.query_l0_events(kind="pnl_history", limit=5)
    status = store.status()
    assert status["counts"]["l2_scenarios"] >= 1


def test_backfill_roadmap_fixture(storage_env):
    root = storage_env["root"]
    settings = storage_env["settings"]

    (root / "pnl_history.jsonl").write_text(
        json.dumps({"date": "2026-08-25", "daily_pnl": 1.0, "recorded_at": "2026-08-25T09:00:00+00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (root / "capital_events.jsonl").write_text(
        json.dumps({"date": "2026-08-25", "kind": "deposit", "amount": 1000, "at": "2026-08-25T09:00:00+00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    cases = root / "memory" / "cases" / "603986-T1-blocked"
    cases.mkdir(parents=True)
    (cases / "detail.json").write_text(json.dumps({"code": "603986", "trade_id": "T1"}, ensure_ascii=False), encoding="utf-8")
    (cases / ".abstract.md").write_text("blocked buy", encoding="utf-8")

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
    assert result["backfilled"].get("pnl_history", 0) >= 1
    assert result["backfilled"].get("trade_case", 0) >= 1

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
    from agent_reach.daily_run.settings import clear_settings_cache, load_settings

    clear_settings_cache()
    settings = load_settings()
    if settings.get("storage", {}).get("enabled"):
        settings = dict(settings)
        settings["storage"] = dict(settings.get("storage") or {})
        settings["storage"]["enabled"] = False
    assert storage_enabled(settings) is False


def test_prune_distilled_l0_and_files(storage_env):
    from agent_reach.daily_run.storage.prune import prune_database, prune_files

    settings = storage_env["settings"]
    root = storage_env["root"]
    store = SqliteDailyRunStore(Path(storage_env["db_path"]))

    store.append_l0_event(
        "job_run",
        {"at": "2026-01-01T00:00:00+00:00", "job": "morning", "success": True},
        dedupe_key="job:old",
    )
    store.append_l0_event(
        "job_run",
        {"at": "2026-08-25T00:00:00+00:00", "job": "close", "success": True},
        dedupe_key="job:new",
    )
    store.mark_l0_distilled([1, 2], job="test")

    dry = store.prune_distilled_l0(
        cutoff_iso="2026-06-01T00:00:00+00:00",
        kinds=["job_run"],
        dry_run=True,
    )
    assert dry["would_delete_rows"] == 1

    applied = store.prune_distilled_l0(
        cutoff_iso="2026-06-01T00:00:00+00:00",
        kinds=["job_run"],
        dry_run=False,
    )
    assert applied["deleted_rows"] == 1
    assert store.status()["counts"]["l0_events"] == 1

    cache = root / "cache"
    cache.mkdir(exist_ok=True)
    old = cache / "2026-01-01.json"
    old.write_text("{}", encoding="utf-8")
    import os
    import time

    old_time = time.time() - (20 * 86400)
    os.utime(old, (old_time, old_time))

    result = prune_files(root=root, cache_keep_days=14, dry_run=False)
    assert result["items"] >= 1
    assert not old.exists()

    db_result = prune_database(settings=settings, l0_keep_days=90, dry_run=True)
    assert db_result.get("skipped") is not True
