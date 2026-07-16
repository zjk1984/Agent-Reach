# -*- coding: utf-8
"""Tests for weekly report generation and split push."""

from datetime import date

from agent_reach.daily_run.report_push import render_weekly_push_sections, split_push_enabled
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.weekly_report import (
    WeeklyReport,
    render_weekly_sections,
    resolve_weekly_portfolio,
    trading_week_range,
)


class TestWeeklyReport:
    def test_trading_week_range_saturday(self):
        start, end = trading_week_range(date(2026, 7, 11))  # Saturday
        assert start.weekday() == 0
        assert end.weekday() == 4

    def test_resolve_weekly_portfolio_from_baseline(self, tmp_path, monkeypatch):
        from datetime import date

        morning = {
            "portfolio": {
                "holdings": [{"code": "688008", "name": "澜起", "shares": 100}],
                "watchlist": [{"code": "603986", "name": "兆易"}],
            }
        }
        dr = tmp_path / ".agent-reach" / "daily_run"
        dr.mkdir(parents=True)
        (dr / "last_morning.json").write_text(__import__("json").dumps(morning), encoding="utf-8")
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_report.Path.home",
            lambda: tmp_path,
        )
        pf, notes = resolve_weekly_portfolio(
            {},
            {"holdings": [], "watchlist": []},
            [],
            week_end=date(2026, 7, 11),
        )
        assert len(pf["holdings"]) == 1
        assert notes

    def test_render_weekly_sections(self):
        report = WeeklyReport(
            week_start=date(2026, 7, 7),
            week_end=date(2026, 7, 11),
            start_total=90000,
            end_total=92000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.22,
            realized_pnl=0,
            holdings=[{"code": "688008", "name": "澜起", "shares": 100, "price": 260, "market_value": 26000}],
        )
        sections = render_weekly_sections(report)
        assert len(sections) >= 2
        push_sections = render_weekly_push_sections(report)
        assert push_sections[0].title.startswith("📋 周报 1/")

    def test_weekly_split_push_enabled(self):
        cfg = load_settings()
        assert split_push_enabled(cfg, report_kind="weekly") is True
