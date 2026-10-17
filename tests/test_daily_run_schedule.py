# -*- coding: utf-8
"""Schedule run --trade-date session override and prod backfill guard."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.run_manifest import save_run_manifest
from agent_reach.daily_run.schedule import (
    ALLOW_PROD_BACKFILL_ENV,
    parse_schedule_trade_date,
    run_scheduled,
    schedule_trade_date_guard_reason,
)
from agent_reach.daily_run.trade_calendar import (
    real_today_shanghai,
    schedule_session_day,
    today_shanghai,
)


class TestScheduleTradeDateParse:
    def test_parse_valid(self):
        assert parse_schedule_trade_date("2026-10-15") == date(2026, 10, 15)

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_schedule_trade_date("10/15/2026")


class TestScheduleSessionDay:
    def test_today_shanghai_override(self):
        session = date(2026, 10, 13)
        assert today_shanghai() == real_today_shanghai()
        with schedule_session_day(session):
            assert today_shanghai() == session
        assert today_shanghai() == real_today_shanghai()

    def test_manifest_path_uses_session_day(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.run_manifest.runs_dir",
            lambda: tmp_path / "runs",
        )
        session = date(2026, 10, 15)
        with schedule_session_day(session):
            path = save_run_manifest("morning", {"job": "morning", "ok": True}, duration_ms=1.0)
        assert path.parent.name == "2026-10-15"
        assert path.name.startswith("morning_")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["date"] == "2026-10-15"


class TestScheduleTradeDateGuard:
    def test_no_trade_date(self):
        assert schedule_trade_date_guard_reason(None) is None

    def test_today_allowed_without_env(self):
        assert schedule_trade_date_guard_reason(real_today_shanghai()) is None

    @patch(
        "agent_reach.daily_run.storage.guard.is_canonical_daily_run_data_root",
        return_value=True,
    )
    def test_historical_blocked_on_canonical_prod(self, _mock_canonical):
        reason = schedule_trade_date_guard_reason(date(2020, 1, 2))
        assert reason is not None
        assert ALLOW_PROD_BACKFILL_ENV in reason

    @patch(
        "agent_reach.daily_run.storage.guard.is_canonical_daily_run_data_root",
        return_value=True,
    )
    def test_historical_allowed_with_env(self, _mock_canonical, monkeypatch):
        monkeypatch.setenv(ALLOW_PROD_BACKFILL_ENV, "1")
        assert schedule_trade_date_guard_reason(date(2020, 1, 2)) is None

    @patch(
        "agent_reach.daily_run.storage.guard.is_canonical_daily_run_data_root",
        return_value=False,
    )
    def test_historical_allowed_off_canonical_root(self, _mock_canonical):
        assert schedule_trade_date_guard_reason(date(2020, 1, 2)) is None


class TestRunScheduledTradeDate:
    @patch(
        "agent_reach.daily_run.storage.guard.is_canonical_daily_run_data_root",
        return_value=True,
    )
    def test_run_scheduled_blocks_historical_without_env(self, _mock_canonical):
        result = run_scheduled("morning", push=False, trade_date=date(2026, 10, 14))
        assert result.get("skipped") is True
        assert result.get("guard") == "trade_date_backfill"

    def test_run_scheduled_writes_manifest_under_trade_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.storage.guard.is_canonical_daily_run_data_root",
            lambda: False,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.run_guard.check_duplicate_job",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.trade_calendar.is_trading_day",
            lambda *a, **k: (True, ""),
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.schedule._uses_per_symbol_jobs",
            lambda settings: False,
        )

        portfolio = {
            "primary_code": "688008",
            "holdings": [{"code": "688008", "name": "x", "shares": 1, "cost": 1.0}],
        }
        snap_path = tmp_path / "morning.json"

        def _load_portfolio():
            return portfolio

        def _build_and_save(**kwargs):
            return ({"code": "688008"}, snap_path)

        def _run_morning(*a, **k):
            return {"snapshot": {"code": "688008"}, "evaluation": {"report": {}}}

        monkeypatch.setattr(
            "agent_reach.daily_run.snapshot_builder.load_portfolio",
            _load_portfolio,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.snapshot_builder.build_and_save",
            _build_and_save,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.workflows.run_morning",
            _run_morning,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.workflows.save_morning_baseline",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.intraday.record_morning_scan",
            lambda *a, **k: {"scan": {"scan_id": "S2"}},
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.run_manifest.runs_dir",
            lambda: tmp_path / "runs",
        )
        session = date(2026, 10, 15)
        result = run_scheduled("morning", push=False, trade_date=session, force=True)
        assert not result.get("skipped")
        manifests = list((tmp_path / "runs" / "2026-10-15").glob("morning_*.json"))
        assert manifests
