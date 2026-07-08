# -*- coding: utf-8
"""Tests for watchlist adjust (morning/close only)."""

import pytest

from agent_reach.daily_run.portfolio_manager import apply_auto_adjust
from agent_reach.daily_run.intraday import TradeDecision
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.watchlist_manager import (
    adjust_watchlist,
    can_adjust_watchlist,
    collect_intraday_sold_codes,
)


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 61000,
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "cost": 255.87}],
        "watchlist": [
            {"code": "603986", "name": "兆易创新"},
            {"code": "002273", "name": "水晶光电"},
        ],
    }


@pytest.fixture
def snapshot(portfolio):
    return {
        "mss_final": 48.0,
        "mss_breakdown": {"fx": 47, "flow": 48, "global": 46, "sentiment": 53},
        "watchlist": [
            {"code": "603986", "name": "兆易创新", "price": 603.17, "change_pct": -2.71},
            {"code": "002273", "name": "水晶光电", "price": 32.04, "change_pct": -6.23},
        ],
        "portfolio": {
            "holdings": [
                {"code": "688008", "name": "澜起科技", "price": 247.15, "change_pct": -2.39},
            ],
        },
    }


@pytest.fixture
def settings():
    s = load_settings()
    s.setdefault("watchlist", {})
    s["watchlist"]["auto_adjust_enabled"] = True
    return s


class TestWatchlistPolicy:
    def test_can_adjust_phases(self):
        assert can_adjust_watchlist("morning") is True
        assert can_adjust_watchlist("close") is True
        assert can_adjust_watchlist("intraday") is False

    def test_intraday_sell_does_not_touch_watchlist(self, portfolio, snapshot):
        settings = load_settings()
        settings["portfolio"] = {"auto_adjust_enabled": True, "max_holdings": 10}
        portfolio["holdings"].append(
            {"code": "002273", "name": "水晶光电", "shares": 300, "cost": 33.81, "days_held": 5}
        )
        snapshot["portfolio"]["holdings"].append(
            {"code": "002273", "name": "水晶光电", "price": 32.04, "change_pct": -6.23}
        )
        before = len(portfolio["watchlist"])
        decision = TradeDecision(
            action="sell",
            trade_id="T1",
            lookback_mss=35.0,
            lookback_detail=[],
            trend="falling",
            reasoning="卖",
        )
        result = apply_auto_adjust(portfolio, decision, snapshot, settings, allow_watchlist_changes=False)
        assert result.applied is True
        assert len(result.portfolio["watchlist"]) == before

    def test_morning_removes_held_from_watchlist(self, portfolio, snapshot, settings):
        portfolio["watchlist"].append({"code": "688008", "name": "澜起科技"})
        result = adjust_watchlist(portfolio, snapshot, settings, "morning")
        assert result.applied is True
        codes = {w["code"] for w in result.portfolio["watchlist"]}
        assert "688008" not in codes

    def test_close_recycles_sold(self, portfolio, snapshot, settings, tmp_path, monkeypatch):
        from agent_reach.daily_run import portfolio_manager

        ledger = tmp_path / "ledger.jsonl"
        ledger.write_text(
            '{"at":"2026-07-08T10:00:00+00:00","actions":[{"side":"sell","code":"002273","name":"水晶光电"}]}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(portfolio_manager, "default_ledger_path", lambda: ledger)
        portfolio["watchlist"] = [{"code": "603986", "name": "兆易创新"}]
        result = adjust_watchlist(
            portfolio,
            snapshot,
            settings,
            "close",
            sold_codes=collect_intraday_sold_codes(settings),
        )
        codes = {w["code"] for w in result.portfolio["watchlist"]}
        assert "002273" in codes

    def test_intraday_phase_rejected(self, portfolio, snapshot, settings):
        result = adjust_watchlist(portfolio, snapshot, settings, "intraday")  # type: ignore[arg-type]
        assert result.applied is False
