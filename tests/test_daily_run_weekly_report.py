# -*- coding: utf-8
"""Tests for weekly report generation and schedule integration."""

import json
from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.weekly_report import (
    _compute_realized_pnl,
    generate_weekly_report,
    render_weekly_markdown,
    trading_week_range,
    weekly_report_title,
)


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 40000,
        "cash_ratio": 0.4,
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100, "cost": 250.0},
            {"code": "002273", "name": "水晶光电", "shares": 300, "cost": 30.0},
        ],
        "watchlist": [
            {"code": "603986", "name": "兆易创新"},
        ],
    }


@pytest.fixture
def snapshot(portfolio):
    return {
        "code": "688008",
        "name": "澜起科技",
        "price": 260.0,
        "change_pct": 2.5,
        "portfolio": portfolio,
        "watchlist": portfolio["watchlist"],
        "holdings": portfolio["holdings"],
    }


class TestTradingWeekRange:
    def test_saturday_returns_previous_week(self):
        sat = date(2026, 7, 11)  # Saturday
        mon, fri = trading_week_range(sat)
        assert mon == date(2026, 7, 6)
        assert fri == date(2026, 7, 10)

    def test_friday_same_week(self):
        fri = date(2026, 7, 10)
        mon, end = trading_week_range(fri)
        assert mon == date(2026, 7, 6)
        assert end == date(2026, 7, 10)


class TestWeeklyReport:
    def test_compute_realized_pnl(self):
        trades = [
            {
                "actions": [
                    {"side": "buy", "amount": 10000, "commission": 15},
                    {"side": "sell", "amount": 10500, "commission": 16},
                ]
            }
        ]
        assert _compute_realized_pnl(trades) == 469.0

    @patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_week_manifests", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[])
    def test_generate_weekly_report(self, mock_ledger, mock_manifests, mock_exa, snapshot, portfolio):
        report = generate_weekly_report(
            snapshot,
            {"weekly_report": {"enabled": True, "exa_sector_research": False}},
            as_of=date(2026, 7, 11),
            portfolio=portfolio,
        )
        assert report.week_start == date(2026, 7, 6)
        assert report.end_total == 100000
        assert len(report.holdings) == 2
        assert len(report.watchlist) == 1
        assert "澜起科技" in render_weekly_markdown(report)
        assert "股市技能学习" in render_weekly_markdown(report)
        assert "流程改进意见" in render_weekly_markdown(report)

    def test_weekly_report_title(self):
        from agent_reach.daily_run.weekly_report import WeeklyReport

        report = WeeklyReport(
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 10),
            start_total=98000,
            end_total=100000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.04,
            realized_pnl=0,
        )
        title = weekly_report_title(report)
        assert "周报" in title
        assert "+¥2,000" in title

    @patch("agent_reach.daily_run.weekly_report._load_manifest")
    @patch("agent_reach.daily_run.weekly_report.runs_dir")
    def test_manifest_pnl_from_close_runs(self, mock_runs_dir, mock_load, tmp_path, snapshot, portfolio):
        day_dir = tmp_path / "2026-07-10"
        day_dir.mkdir()
        morning_dir = tmp_path / "2026-07-06"
        morning_dir.mkdir()
        mock_runs_dir.return_value = tmp_path

        morning_manifest = {
            "job": "morning",
            "payload": {
                "result": {
                    "snapshot": {"portfolio": {"total": 98000}},
                }
            },
        }
        close_manifest = {
            "job": "close",
            "payload": {
                "result": {
                    "snapshot": {"portfolio": {"total": 100500}, "mss_final": 48},
                }
            },
        }

        def _load_side_effect(path):
            name = path.name
            if "morning" in name:
                return morning_manifest
            if "close" in name:
                return close_manifest
            return None

        (morning_dir / "morning_080000.json").write_text("{}", encoding="utf-8")
        (day_dir / "close_153000.json").write_text("{}", encoding="utf-8")
        mock_load.side_effect = _load_side_effect

        with patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[]):
            with patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[]):
                report = generate_weekly_report(
                    snapshot,
                    {"weekly_report": {"exa_sector_research": False}},
                    as_of=date(2026, 7, 11),
                    portfolio=portfolio,
                )

        assert report.start_total == 98000
        assert report.end_total == 100500
        assert report.weekly_pnl == 2500


class TestScheduleWeekly:
    @patch("agent_reach.daily_run.workflows.run_weekly")
    @patch("agent_reach.daily_run.snapshot_builder.build_and_save")
    @patch("agent_reach.daily_run.snapshot_builder.load_portfolio")
    def test_run_scheduled_weekly_skips_trading_day_check(
        self, mock_load, mock_build, mock_run_weekly, portfolio, tmp_path
    ):
        from agent_reach.daily_run.schedule import run_scheduled

        mock_load.return_value = portfolio
        mock_build.return_value = ({"code": "688008"}, tmp_path / "snap.json")
        mock_run_weekly.return_value = {
            "steps": ["generate", "render"],
            "report": {"weekly_pnl": 1000},
            "markdown": "weekly",
        }

        with patch("agent_reach.daily_run.trade_calendar.is_trading_day", return_value=(False, "周末")):
            result = run_scheduled("weekly", push=False)

        assert result["job"] == "weekly"
        assert not result.get("skipped")
        mock_run_weekly.assert_called_once()

    def test_default_entries_includes_weekly(self):
        from agent_reach.daily_run.schedule import default_entries

        entries = default_entries()
        assert len(entries) == 15
        assert any("weekly" in e.job for e in entries)
        assert any("forecast" in e.job for e in entries)
        assert any(e.weekday == "6" and e.hour == "9" for e in entries)
        assert any(e.weekday == "0" and e.hour == "9" for e in entries)

    def test_render_crontab_includes_weekly(self):
        from agent_reach.daily_run.schedule import render_crontab_block

        block = render_crontab_block()
        assert "schedule run weekly" in block
        assert "0 9 * * 6" in block
