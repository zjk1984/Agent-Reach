# -*- coding: utf-8
"""Forecast miss streak skips schedule-gap days without actuals."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from agent_reach.daily_run.forecast_miss_overlay import forecast_mss_miss_streak


def test_miss_streak_skips_days_without_actuals():
    forecast = {
        "trading_days": ["2026-10-13", "2026-10-14", "2026-10-15"],
        "actuals": {
            "2026-10-15": {"mss_hit": False},
            # 10-14 gap: no row
            "2026-10-13": {"mss_hit": False},
        },
    }
    with patch(
        "agent_reach.daily_run.week_forecast.load_active_forecast",
        lambda d: forecast,
    ):
        streak = forecast_mss_miss_streak(as_of=date(2026, 10, 15))
    assert streak == 2
