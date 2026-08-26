# -*- coding: utf-8
"""Tests for storage read-through facade."""

from __future__ import annotations

import pytest

from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history
from agent_reach.daily_run.realized_pnl import load_ledger_entries
from agent_reach.daily_run.storage import reset_store
from agent_reach.daily_run.storage.distill import run_distill
from agent_reach.daily_run.storage.hooks import (
    on_daily_pnl,
    on_trade_ledger,
)
from agent_reach.daily_run.storage.readers import (
    read_daily_pnl_records,
    read_harness_state_payload,
    read_intraday_trade_records_for_day,
    read_latest_portfolio,
    read_trade_ledger_entries,
)


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    db_path = tmp_path / "daily_run.db"
    settings = {
        "storage": {
            "enabled": True,
            "backend": "sqlite",
            "sqlite_path": str(db_path),
            "read_prefer_db": True,
            "distill": {"enabled": True, "auto_after_close": False},
        }
    }
    monkeypatch.setenv("AGENT_REACH_STORAGE", "1")
    monkeypatch.setattr(
        "agent_reach.daily_run.settings.load_settings",
        lambda path=None: settings,
    )
    reset_store()
    yield {"settings": settings}
    reset_store()


def test_read_trade_ledger_entries(storage_env):
    settings = storage_env["settings"]
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
                }
            ],
        }
    )
    rows = read_trade_ledger_entries(settings=settings)
    assert rows
    assert rows[0]["trade_id"] == "T1"


def test_load_ledger_entries_prefers_db(storage_env):
    settings = storage_env["settings"]
    on_trade_ledger(
        {
            "at": "2026-08-25T09:00:00+00:00",
            "trade_id": "T2",
            "decision_action": "sell",
            "actions": [{"side": "sell", "code": "603986", "shares": 50, "price": 125.0}],
        }
    )
    rows = load_ledger_entries(settings=settings)
    assert any(row.get("trade_id") == "T2" for row in rows)


def test_read_daily_pnl_and_load_history(storage_env):
    settings = storage_env["settings"]
    on_daily_pnl(
        {
            "date": "2026-08-25",
            "daily_pnl": 120.5,
            "daily_pnl_pct": 0.12,
            "recorded_at": "2026-08-25T15:00:00+00:00",
        }
    )
    raw = read_daily_pnl_records(settings=settings)
    assert raw and raw[0]["date"] == "2026-08-25"
    rows = load_daily_pnl_history(settings=settings)
    assert rows and rows[0].date == "2026-08-25"


def test_read_latest_portfolio(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage import get_store

    get_store(settings).upsert_portfolio(
        {
            "cash": 50000.0,
            "total": 120000.0,
            "holdings": [{"code": "603986", "name": "兆易创新", "shares": 100, "cost": 120.5}],
        },
        source="test",
    )
    pf = read_latest_portfolio(settings=settings)
    assert pf and float(pf["cash"]) == 50000.0


def test_read_intraday_trade_records_for_day(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage import get_store

    store = get_store(settings)
    store.upsert_l2_scenario(
        "trade_case",
        "case-1",
        {
            "action": "buy",
            "code": "002583",
            "as_of": "2026-08-25T06:30:00+00:00",
            "trade_id": "T3",
        },
        code="002583",
        at="2026-08-25",
        title="case-1",
        content="buy",
        dedupe_key="l2:trade_case:case-1",
    )
    rows = read_intraday_trade_records_for_day("2026-08-25", settings=settings)
    assert rows and rows[0]["trade_id"] == "T3"


def test_read_harness_state_payload(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage import get_store

    get_store(settings).sync_harness_state(
        {
            "updated_at": "2026-08-25T10:00:00+00:00",
            "entries": {
                "memory": {
                    "m1": {
                        "id": "m1",
                        "title": "test",
                        "content": "hello",
                        "updated_at": "2026-08-25T10:00:00+00:00",
                    }
                }
            },
        }
    )
    payload = read_harness_state_payload(settings=settings)
    assert payload and payload["entries"]["memory"]["m1"]["content"] == "hello"
