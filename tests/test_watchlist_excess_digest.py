# -*- coding: utf-8
"""M11 — watchlist T+3/T+5 excess digest."""

from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.trade_calendar import trading_day_after
from agent_reach.daily_run.watchlist_excess_digest import (
    build_watchlist_excess_digest,
    collect_watchlist_add_events,
    render_watchlist_excess_markdown,
    symbol_close_from_manifests,
    watchlist_excess_digest_enabled,
)


def _settings(enabled: bool = True) -> dict:
    return {
        "trade_calendar": {"enabled": False},
        "watchlist": {
            "excess_digest": {
                "enabled": enabled,
                "lookback_trading_days": 20,
                "horizons": [3, 5],
            }
        },
    }


def _manifest(day: str, code: str, price: float, *, job: str = "close") -> dict:
    return {
        "_run_date": day,
        "job": job,
        "payload": {
            "watchlist_adjust": {
                "applied": True,
                "changes": [
                    {
                        "action": "add",
                        "code": code,
                        "name": "测试股",
                        "reason": "weekly候选",
                    }
                ],
            },
            "symbol_results": [
                {
                    "code": code,
                    "result": {"snapshot": {"code": code, "price": price}},
                }
            ],
        },
    }


class TestTradingDayAfter:
    def test_three_sessions_after(self):
        settings = {"trade_calendar": {"enabled": False}}
        start = date(2026, 7, 6)  # Monday
        assert trading_day_after(start, 3, settings=settings) == date(2026, 7, 9)


class TestCollectAdds:
    def test_dedupes_day_code(self):
        manifests = [
            _manifest("2026-07-07", "603986", 100.0),
            _manifest("2026-07-07", "603986", 101.0),
        ]
        events = collect_watchlist_add_events(
            manifests,
            window_start=date(2026, 7, 1),
            window_end=date(2026, 7, 10),
        )
        assert len(events) == 1
        assert events[0]["code"] == "603986"


class TestBuildDigest:
    @patch("agent_reach.daily_run.watchlist_excess_digest.fetch_benchmark_period_return")
    def test_t3_excess_computed(self, mock_bench):
        mock_bench.return_value = {"ok": True, "return_pct": 1.0, "name": "沪深300"}
        entry_day = "2026-07-06"
        t3_day = "2026-07-09"
        manifests = [
            _manifest(entry_day, "603986", 100.0),
            {
                "_run_date": t3_day,
                "job": "close",
                "payload": {
                    "symbol_results": [
                        {
                            "code": "603986",
                            "result": {"snapshot": {"code": "603986", "price": 106.0}},
                        }
                    ],
                },
            },
        ]

        def prices(code: str, day: date) -> float | None:
            if code == "603986" and day.isoformat() == entry_day:
                return 100.0
            if code == "603986" and day.isoformat() == t3_day:
                return 106.0
            return symbol_close_from_manifests(code, day, manifests)

        digest = build_watchlist_excess_digest(
            manifests=manifests,
            as_of=date(2026, 7, 10),
            settings=_settings(),
            price_resolver=prices,
        )
        assert digest.enabled
        assert len(digest.events) == 1
        row = digest.events[0]
        assert row["t3_status"] == "matured"
        assert row["t3_stock_pct"] == pytest.approx(6.0)
        assert row["t3_excess_pct"] == pytest.approx(5.0)
        assert digest.horizons[0]["avg_excess_pct"] == pytest.approx(5.0)

    def test_disabled_by_default(self):
        digest = build_watchlist_excess_digest(
            manifests=[],
            as_of=date(2026, 7, 10),
            settings=_settings(enabled=False),
        )
        assert digest.enabled is False
        assert not watchlist_excess_digest_enabled(_settings(enabled=False))

    def test_markdown_contains_heading(self):
        digest = build_watchlist_excess_digest(
            manifests=[],
            as_of=date(2026, 7, 10),
            settings=_settings(enabled=False),
        )
        assert render_watchlist_excess_markdown(digest) == ""