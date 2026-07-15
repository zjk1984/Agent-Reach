# -*- coding: utf-8
"""Tests for Sunday week forecast generation and split push."""

from datetime import date

from agent_reach.daily_run.report_push import render_forecast_push_sections, split_push_enabled
from agent_reach.daily_run.week_forecast import (
    generate_week_forecast,
    next_trading_week_range,
    render_forecast_sections,
)
from agent_reach.daily_run.weekly_digest import load_weekly_digest, save_weekly_digest
from agent_reach.daily_run.settings import load_settings


class TestWeekForecast:
    def test_next_trading_week_from_sunday(self):
        sunday = date(2026, 7, 12)
        mon, fri = next_trading_week_range(sunday)
        assert mon.weekday() == 0
        assert fri.weekday() == 4
        assert (fri - mon).days == 4

    def test_generate_forecast_minimal(self):
        snap = {
            "code": "688008",
            "name": "澜起科技",
            "price": 100,
            "portfolio": {
                "holdings": [{"code": "688008", "name": "澜起科技", "price": 100, "change_pct": 1.2}],
                "watchlist": [],
            },
        }
        forecast = generate_week_forecast(snap, load_settings())
        sections = render_forecast_sections(forecast)
        assert len(sections) >= 2
        assert "688008" in forecast.symbols
        push_sections = render_forecast_push_sections(forecast)
        assert len(push_sections) == len(sections)
        assert all(s.title.startswith("🔮") for s in push_sections)

    def test_forecast_split_push_enabled(self):
        cfg = load_settings()
        assert split_push_enabled(cfg, report_kind="forecast") is True

    def test_load_weekly_digest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_digest.digest_path",
            lambda: tmp_path / "weekly_digest.json",
        )
        save_weekly_digest({"week_end": "2026-07-11", "hot_sectors": [{"sector": "半导体"}]})
        loaded = load_weekly_digest()
        assert loaded is not None
        assert loaded["hot_sectors"][0]["sector"] == "半导体"
