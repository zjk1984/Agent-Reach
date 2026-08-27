# -*- coding: utf-8
"""Tests for trade_calendar continuous-session gate and trading_day_before backfill."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_reach.daily_run.trade_calendar import is_continuous_session, trading_day_before

_SH_TZ = ZoneInfo("Asia/Shanghai")


class TestIsContinuousSession:
    def test_morning_session(self):
        dt = datetime(2026, 8, 24, 10, 0, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is True

    def test_afternoon_session(self):
        dt = datetime(2026, 8, 24, 13, 30, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is True

    def test_before_open_call_auction(self):
        dt = datetime(2026, 8, 24, 9, 20, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is False

    def test_lunch_break(self):
        dt = datetime(2026, 8, 24, 12, 0, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is False

    def test_is_lunch_break_helper(self):
        from agent_reach.daily_run.trade_calendar import is_lunch_break

        assert is_lunch_break(datetime(2026, 8, 24, 12, 30, tzinfo=_SH_TZ)) is True
        assert is_lunch_break(datetime(2026, 8, 24, 13, 0, tzinfo=_SH_TZ)) is False

    def test_closing_call_auction_excluded(self):
        dt = datetime(2026, 8, 24, 14, 58, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is False

    def test_after_close(self):
        dt = datetime(2026, 8, 24, 15, 5, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is False

    def test_naive_datetime_treated_as_shanghai(self):
        dt = datetime(2026, 8, 24, 10, 0)
        assert is_continuous_session(dt) is True

    def test_boundary_exact_open(self):
        dt = datetime(2026, 8, 24, 9, 30, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is True

    def test_boundary_exact_close(self):
        dt = datetime(2026, 8, 24, 11, 30, tzinfo=_SH_TZ)
        assert is_continuous_session(dt) is False

    def test_default_uses_now(self):
        with patch(
            "agent_reach.daily_run.trade_calendar.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 24, 10, 0, tzinfo=_SH_TZ)
            assert is_continuous_session() is True


class TestTradingDayBefore:
    def test_zero_or_negative_returns_as_of(self):
        d = date(2026, 8, 24)
        assert trading_day_before(d, 0) == d
        assert trading_day_before(d, -3) == d

    def test_fallback_walks_back_weekdays_without_calendar(self):
        with patch("agent_reach.daily_run.trade_calendar._load_trade_dates_akshare", return_value=set()):
            # 2026-08-24 is a Monday; 1 trading day before -> previous Friday.
            result = trading_day_before(date(2026, 8, 24), 1)
            assert result == date(2026, 8, 21)

    def test_fallback_multiple_days(self):
        with patch("agent_reach.daily_run.trade_calendar._load_trade_dates_akshare", return_value=set()):
            result = trading_day_before(date(2026, 8, 24), 3)
            assert result == date(2026, 8, 19)

    def test_uses_akshare_calendar_when_available(self):
        trade_dates = {"2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"}
        with patch(
            "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
            return_value=trade_dates,
        ):
            assert trading_day_before(date(2026, 8, 24), 1) == date(2026, 8, 21)
            assert trading_day_before(date(2026, 8, 24), 3) == date(2026, 8, 19)

    def test_akshare_calendar_clamps_to_earliest_when_n_too_large(self):
        trade_dates = {"2026-08-20", "2026-08-21", "2026-08-24"}
        with patch(
            "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
            return_value=trade_dates,
        ):
            assert trading_day_before(date(2026, 8, 24), 100) == date(2026, 8, 20)
