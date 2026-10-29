# -*- coding: utf-8
"""Daily session change_pct resolution (Wind / prev-close semantics)."""

from datetime import date
from agent_reach.daily_run.forecast_tracking import build_kronos_divergence_day_checks
from agent_reach.daily_run.symbols import resolve_daily_change_pct
from agent_reach.daily_run.week_forecast_tracker import evaluate_day_forecast


def test_resolve_daily_change_prefers_prev_close_over_stale_quote():
    """海康-style: stale +3.23% quote vs Wind -2.11% from prev close."""
    row = {
        "code": "002415",
        "name": "海康威视",
        "price": 34.87,
        "prev_close": 35.62,
        "change_pct": 3.23,
    }
    assert resolve_daily_change_pct(row) == -2.11


def test_evaluate_day_forecast_uses_resolved_daily_change():
    forecast = {
        "symbols": {
            "002415": {
                "name": "海康威视",
                "role": "holding",
                "days": {
                    "2026-10-28": {
                        "direction": "down",
                        "change_pct_range": [-3.0, 0.0],
                        "expected_change_pct": -1.0,
                    }
                },
            }
        },
    }
    enriched = {
        "002415": {
            "price": 34.87,
            "prev_close": 35.62,
            "change_pct": 3.23,
        }
    }
    review = evaluate_day_forecast(
        forecast,
        {"portfolio": {"holdings": []}},
        date(2026, 10, 28),
        enriched=enriched,
    )
    ev = review.symbol_evals[0]
    assert ev.actual_change_pct == -2.11
    assert ev.predicted_direction == "down"


def test_kronos_divergence_day_uses_resolved_actual(monkeypatch):
    from agent_reach.daily_run.quote_fetch import QuoteFetchResult

    monkeypatch.setattr(
        "agent_reach.daily_run.quote_fetch.fetch_quotes_map",
        lambda codes, **_: QuoteFetchResult(),
    )
    forecast = {
        "trading_days": ["2026-10-28"],
        "symbols": {
            "002415": {
                "name": "海康威视",
                "kronos_divergence_days": ["2026-10-28"],
                "days": {"2026-10-28": {"kronos_change_pct": -1.2}},
            }
        },
    }
    snapshot = {
        "portfolio": {
            "holdings": [
                {
                    "code": "002415",
                    "price": 34.87,
                    "prev_close": 35.62,
                    "change_pct": 3.23,
                }
            ]
        }
    }
    checks = build_kronos_divergence_day_checks(
        forecast,
        snapshot,
        trading_date=date(2026, 10, 28),
    )
    assert len(checks) == 1
    assert checks[0]["actual_direction"] == "down"
    assert "实际 ↓（-2.11%）" in checks[0]["text"]
