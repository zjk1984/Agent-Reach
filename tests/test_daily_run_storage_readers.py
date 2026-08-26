# -*- coding: utf-8
"""Tests for storage read-through facade."""

from __future__ import annotations

import json

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
    read_capital_events,
    read_daily_cache,
    read_daily_pnl_records,
    read_daily_trade_state,
    read_experience_entries,
    read_harness_state_payload,
    read_intraday_trade_records_for_day,
    read_job_health,
    read_last_snapshot,
    read_latest_portfolio,
    read_morning_baseline_from_store,
    read_pnl_target_state,
    read_rejected_strategies,
    read_runtime_overlay,
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


def test_load_portfolio_prefers_file_when_db_truncated(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_builder import load_portfolio
    from agent_reach.daily_run.storage import get_store
    from agent_reach.daily_run.symbols import resolve_target_symbols

    settings = storage_env["settings"]
    root = tmp_path / "daily_run"
    root.mkdir(parents=True, exist_ok=True)
    pf_path = root / "portfolio.json"
    full = {
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100},
            {"code": "002583", "name": "海能达", "shares": 2500},
            {"code": "000725", "name": "京东方A", "shares": 900},
        ],
        "watchlist": [
            {"code": "603986", "name": "兆易创新"},
            {"code": "002415", "name": "海康威视"},
            {"code": "601138", "name": "工业富联"},
            {"code": "300308", "name": "中际旭创"},
            {"code": "002273", "name": "水晶光电"},
            {"code": "600584", "name": "长电科技"},
        ],
        "cash": 50000.0,
        "total": 110000.0,
        "primary_code": "688008",
    }
    pf_path.write_text(json.dumps(full, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_builder.default_portfolio_path",
        lambda: pf_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    get_store(settings).upsert_portfolio(
        {
            "holdings": [],
            "watchlist": [{"code": "000725", "name": "京东方A"}],
            "cash": 40000.0,
            "total": 90000.0,
        },
        source="test",
    )

    loaded = load_portfolio(settings=settings)
    assert len(loaded.get("holdings") or []) == 3
    assert len(loaded.get("watchlist") or []) == 6
    codes = resolve_target_symbols(
        loaded,
        {**settings, "schedule": {"symbols_mode": "all", "intraday_symbols_mode": "all"}},
        workflow="intraday",
    )
    assert len(codes) == 9
    assert codes == [
        "688008",
        "002583",
        "000725",
        "603986",
        "002415",
        "601138",
        "300308",
        "002273",
        "600584",
    ]

    db_after = get_store(settings).query_latest_portfolio_snapshot()
    assert db_after
    assert len(db_after.get("holdings") or []) == 3
    assert len(db_after.get("watchlist") or []) == 6
    assert db_after.get("_snapshot_source") == "repair"


def test_load_portfolio_uses_db_when_file_not_broader(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_builder import load_portfolio

    settings = storage_env["settings"]
    root = tmp_path / "daily_run"
    root.mkdir(parents=True, exist_ok=True)
    pf_path = root / "portfolio.json"
    file_pf = {
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100}],
        "watchlist": [],
        "cash": 50000.0,
        "total": 100000.0,
    }
    pf_path.write_text(json.dumps(file_pf, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_builder.default_portfolio_path",
        lambda: pf_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    db_pf = {
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100}],
        "watchlist": [{"code": "603986", "name": "兆易创新"}],
        "cash": 48000.0,
        "total": 98000.0,
    }
    get_store = __import__(
        "agent_reach.daily_run.storage", fromlist=["get_store"]
    ).get_store
    get_store(settings).upsert_portfolio(db_pf, source="test")

    loaded = load_portfolio(settings=settings)
    assert float(loaded["cash"]) == 48000.0
    assert any(row.get("code") == "603986" for row in loaded.get("watchlist") or [])


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


def test_read_job_run_manifests(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_job_run

    on_job_run(
        {
            "job": "close",
            "date": "2026-08-25",
            "at": "2026-08-25T07:00:00+00:00",
            "payload": {"result": {"snapshot": {"code": "603986", "mss_final": 50.0}}},
        },
        source_path="/tmp/close_070000.json",
    )
    from agent_reach.daily_run.storage.readers import read_job_run_manifests
    from datetime import date

    rows = read_job_run_manifests(date(2026, 8, 25), date(2026, 8, 25), settings=settings)
    assert rows and rows[0]["job"] == "close"
    assert rows[0]["_run_date"] == "2026-08-25"


def test_read_week_forecast(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage import get_store
    from agent_reach.daily_run.storage.readers import read_week_forecast
    from datetime import date

    get_store(settings).upsert_l2_scenario(
        "forecast",
        "2026-08-25",
        {"week_start": "2026-08-25", "week_end": "2026-08-29", "summary": "test"},
        at="2026-08-25",
        title="week forecast",
        content="test",
        dedupe_key="l2:forecast:2026-08-25",
    )
    payload = read_week_forecast(date(2026, 8, 25), settings=settings)
    assert payload and payload.get("summary") == "test"


def test_read_experience_entries(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_experience_entry
    from agent_reach.daily_run.storage.readers import read_experience_entries

    on_experience_entry(
        {
            "date": "2026-08-25",
            "at": "2026-08-25T07:30:00+00:00",
            "code": "603986",
            "name": "兆易创新",
            "mss_final": 51.0,
            "rules": ["rule-a"],
        }
    )
    rows = read_experience_entries(settings=settings, limit=5)
    assert rows and rows[0]["code"] == "603986"


def test_read_capital_events(storage_env):
    settings = storage_env["settings"]
    from datetime import date

    from agent_reach.daily_run.storage.hooks import on_capital_event

    on_capital_event(
        {
            "date": "2026-08-25",
            "kind": "deposit",
            "amount": 30000.0,
            "note": "test",
            "at": "2026-08-25T09:00:00+00:00",
        }
    )
    rows = read_capital_events(
        settings=settings,
        start=date(2026, 8, 25),
        end=date(2026, 8, 25),
    )
    assert rows and rows[0]["kind"] == "deposit"


def test_read_daily_trade_state(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_l1_state

    on_l1_state(
        "daily_trade_state",
        "daily_trade_state",
        {"date": "2026-08-25", "fingerprints": ["abc"]},
        at="2026-08-25T09:00:00+00:00",
    )
    payload = read_daily_trade_state(settings=settings)
    assert payload and payload.get("fingerprints") == ["abc"]


def test_read_rejected_strategies(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_rejected_strategy

    on_rejected_strategy({"id": "r1", "title": "bad idea", "reason": "failed"})
    rows = read_rejected_strategies(settings=settings, limit=5)
    assert rows and rows[0]["title"] == "bad idea"


def test_read_morning_baseline_from_store(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage import get_store

    get_store(settings).upsert_l2_scenario(
        "baseline_morning",
        "morning/603986",
        {"code": "603986", "mss_final": 52.0, "report_type": "premarket"},
        code="603986",
        at="2026-08-25",
        title="morning baseline",
        content="mss=52",
        dedupe_key="l2:baseline:morning:603986:2026-08-25",
    )
    payload = read_morning_baseline_from_store("603986", settings=settings)
    assert payload and float(payload["mss_final"]) == 52.0


def test_load_capital_events_prefers_db(storage_env):
    from agent_reach.daily_run.capital_events import load_capital_events
    from agent_reach.daily_run.storage.hooks import on_capital_event
    from datetime import date

    settings = storage_env["settings"]
    on_capital_event(
        {
            "date": "2026-08-25",
            "kind": "withdraw",
            "amount": 5000.0,
            "at": "2026-08-25T10:00:00+00:00",
        }
    )
    rows = load_capital_events(
        settings=settings,
        start=date(2026, 8, 25),
        end=date(2026, 8, 25),
    )
    assert rows and rows[0].kind == "withdraw"


def test_read_runtime_overlay(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_runtime_overlay

    on_runtime_overlay(
        {
            "threshold_overlay": {"min_mss": 45.0},
            "updated_at": "2026-08-25T10:00:00+00:00",
        },
        source_path="/tmp/last_runtime_overlay.json",
    )
    payload = read_runtime_overlay(settings=settings)
    assert payload and payload["threshold_overlay"]["min_mss"] == 45.0


def test_load_last_runtime_overlay_prefers_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.context_layers import load_last_runtime_overlay
    from agent_reach.daily_run.storage.hooks import on_runtime_overlay

    root = tmp_path / "daily_run"
    overlay_path = root / "harness" / "last_runtime_overlay.json"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text('{"runtime_overlay": {"stale": true}}\n', encoding="utf-8")
    monkeypatch.setattr(
        "agent_reach.daily_run.context_layers._last_overlay_path",
        lambda: overlay_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    on_runtime_overlay(
        {"runtime_overlay": {"foo": "bar"}, "updated_at": "2026-08-25T10:00:00+00:00"},
        source_path=str(overlay_path),
    )
    overlay = load_last_runtime_overlay()
    assert overlay.get("runtime_overlay", {}).get("foo") == "bar"


def test_read_job_health(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_l1_state

    on_l1_state(
        "job_health",
        "job_health",
        {"jobs": {"close": {"consecutive_failures": 2, "last_error": "timeout"}}},
    )
    payload = read_job_health(settings=settings)
    assert payload and payload["jobs"]["close"]["consecutive_failures"] == 2


def test_job_health_load_prefers_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.job_health import _load
    from agent_reach.daily_run.storage.hooks import on_l1_state

    root = tmp_path / "daily_run"
    health_file = root / "job_health.json"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text(
        '{"jobs": {"morning": {"consecutive_failures": 99, "last_error": "stale"}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_reach.daily_run.job_health.health_path", lambda: health_file)
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    on_l1_state(
        "job_health",
        "job_health",
        {"jobs": {"morning": {"consecutive_failures": 1, "last_error": "api"}}},
    )
    data = _load()
    assert data["jobs"]["morning"]["consecutive_failures"] == 1


def test_read_pnl_target_state(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_l1_state

    on_l1_state(
        "pnl_target",
        "pnl_target",
        {
            "pending": {"target_date": "2026-08-26", "target_pnl_cny": 500.0},
            "last_result": None,
            "history": [],
        },
    )
    payload = read_pnl_target_state(settings=settings)
    assert payload and payload["pending"]["target_pnl_cny"] == 500.0


def test_load_pnl_target_state_prefers_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.pnl_target import load_pnl_target_state
    from agent_reach.daily_run.storage.hooks import on_l1_state

    root = tmp_path / "daily_run"
    target_file = root / "pnl_target.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(
        '{"pending": {"target_date": "2026-08-01", "target_pnl_cny": 1.0}, '
        '"last_result": null, "history": []}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.pnl_target.default_pnl_target_path",
        lambda: target_file,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    on_l1_state(
        "pnl_target",
        "pnl_target",
        {
            "pending": {"target_date": "2026-08-27", "target_pnl_cny": 600.0},
            "last_result": None,
            "history": [],
        },
    )
    state = load_pnl_target_state()
    assert state["pending"]["target_pnl_cny"] == 600.0


def test_read_last_snapshot(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_last_snapshot

    on_last_snapshot(
        {"code": "603986", "price": 120.5, "as_of": "2026-08-25T09:00:00+00:00"},
        source_path="/tmp/last_snapshot.json",
    )
    payload = read_last_snapshot(settings=settings)
    assert payload and payload["code"] == "603986"


def test_load_last_snapshot_prefers_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_cache import load_last_snapshot, save_last_snapshot
    from agent_reach.daily_run.storage.hooks import on_last_snapshot

    root = tmp_path / "daily_run"
    snap_path = root / "last_snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text('{"code": "stale", "price": 1.0}\n', encoding="utf-8")
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_cache.last_snapshot_path",
        lambda: snap_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    on_last_snapshot(
        {"code": "603986", "price": 120.5, "as_of": "2026-08-25T09:00:00+00:00"},
        source_path=str(snap_path),
    )
    snap = load_last_snapshot()
    assert snap and snap["code"] == "603986"


def test_save_last_snapshot_writes_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_cache import save_last_snapshot

    root = tmp_path / "daily_run"
    snap_path = root / "last_snapshot.json"
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_cache.last_snapshot_path",
        lambda: snap_path,
    )
    settings = storage_env["settings"]
    save_last_snapshot({"code": "002583", "price": 7.95, "as_of": "2026-08-25"})
    payload = read_last_snapshot(settings=settings)
    assert payload and payload["code"] == "002583"


def test_read_daily_cache(storage_env):
    settings = storage_env["settings"]
    from agent_reach.daily_run.storage.hooks import on_daily_cache

    on_daily_cache(
        {"macro_ctx": {"macro_summary": "risk-on"}, "technicals": {"603986": {"ma20": 120.0}}},
        day="2026-08-25",
        source_path="/tmp/cache/2026-08-25.json",
    )
    payload = read_daily_cache("2026-08-25", settings=settings)
    assert payload and payload["macro_ctx"]["macro_summary"] == "risk-on"


def test_load_daily_cache_prefers_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_cache import load_daily_cache
    from agent_reach.daily_run.storage.hooks import on_daily_cache

    root = tmp_path / "daily_run"
    cache_root = root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_file = cache_root / "2026-08-25.json"
    cache_file.write_text('{"macro_ctx": {"macro_summary": "stale"}}\n', encoding="utf-8")
    monkeypatch.setattr("agent_reach.daily_run.snapshot_cache.cache_dir", lambda: cache_root)
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_cache._cache_day",
        lambda d=None: "2026-08-25",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root,
    )

    on_daily_cache(
        {"macro_ctx": {"macro_summary": "fresh"}},
        day="2026-08-25",
        source_path=str(cache_file),
    )
    data = load_daily_cache()
    assert data["macro_ctx"]["macro_summary"] == "fresh"


def test_save_daily_cache_writes_db(storage_env, tmp_path, monkeypatch):
    from agent_reach.daily_run.snapshot_cache import save_daily_cache

    root = tmp_path / "daily_run" / "cache"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("agent_reach.daily_run.snapshot_cache.cache_dir", lambda: root)
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_cache._cache_day",
        lambda d=None: "2026-08-26",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.storage.config.daily_run_data_root",
        lambda: root.parent,
    )
    settings = storage_env["settings"]
    save_daily_cache({"technicals": {"603986": {"ma20": 121.0}}})
    payload = read_daily_cache("2026-08-26", settings=settings)
    assert payload and payload["technicals"]["603986"]["ma20"] == 121.0
