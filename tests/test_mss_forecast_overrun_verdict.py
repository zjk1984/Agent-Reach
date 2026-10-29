# -*- coding: utf-8
"""AR-23: MSS forecast upper overrun → intraday verdict ceiling lift."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_reach.daily_run.intraday import _decide_trade
from agent_reach.daily_run.mss_forecast import (
    consecutive_forecast_overrun_slots,
    forecast_overrun_ceiling_lifted,
)
from agent_reach.daily_run.pipeline import evaluate_snapshot
from agent_reach.daily_run.verdict import VerdictResult, apply_intraday_macro_verdict_ceiling


def _forecast(upper: float = 44.9) -> dict:
    return {
        "week_start": "2026-10-27",
        "week_end": "2026-10-31",
        "trading_days": ["2026-10-27", "2026-10-28", "2026-10-29"],
        "mss_daily": {
            "2026-10-29": {"range": [36.0, upper], "median": 40.0},
        },
    }


def _gating_settings(**overrun) -> dict:
    intraday = {
        "mss_forecast_overrun": {
            "enabled": True,
            "overrun_pts": 8,
            "consecutive_slots": 2,
            **overrun,
        },
    }
    return {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 55, "min_cash_ratio": 0.0},
        "verdict_labels": {"buy": "可做", "watch": "观察", "avoid": "回避"},
        "intraday": intraday,
        "harness_runtime": {
            "trade_signals": {"defensive_trim": True, "mss_forecast_miss": True},
        },
    }


def _snapshot(mss: float = 54.0) -> dict:
    return {
        "code": "688008",
        "name": "澜起科技",
        "report_type": "intraday",
        "mss_final": mss,
        "price": 220.0,
        "ma20": 210.0,
        "position_20d": 0.5,
        "volume_ratio": 1.2,
        "audit_passed": True,
        "structured_review_complete": True,
        "mss_breakdown": {"technical": 60, "macro": 55, "sentiment": 50},
    }


@patch("agent_reach.daily_run.week_forecast.load_active_forecast", return_value=_forecast())
@patch("agent_reach.daily_run.trade_calendar.today_shanghai")
def test_below_threshold_no_lift(mock_today, _load_fc):
    from datetime import date

    mock_today.return_value = date(2026, 10, 29)
    settings = _gating_settings()
    scans = [{"scan_id": "S1", "mss_final": 50.0}, {"scan_id": "S2", "mss_final": 51.0}]
    assert consecutive_forecast_overrun_slots(scans, settings) == 0
    assert not forecast_overrun_ceiling_lifted(scans, settings)


@patch("agent_reach.daily_run.week_forecast.load_active_forecast", return_value=_forecast())
@patch("agent_reach.daily_run.trade_calendar.today_shanghai")
def test_one_slot_overrun_no_lift(mock_today, _load_fc):
    from datetime import date

    mock_today.return_value = date(2026, 10, 29)
    settings = _gating_settings()
    scans = [{"scan_id": "S1", "mss_final": 51.0}, {"scan_id": "S2", "mss_final": 55.0}]
    streak = consecutive_forecast_overrun_slots(scans, settings)
    assert streak == 1
    assert not forecast_overrun_ceiling_lifted(scans, settings)


@patch("agent_reach.daily_run.week_forecast.load_active_forecast", return_value=_forecast())
@patch("agent_reach.daily_run.trade_calendar.today_shanghai")
def test_two_slots_lift_verdict_to_buy(mock_today, _load_fc):
    from datetime import date

    mock_today.return_value = date(2026, 10, 29)
    settings = _gating_settings()
    scans = [
        {"scan_id": "S1", "mss_final": 54.0},
        {"scan_id": "S2", "mss_final": 54.2},
        {"scan_id": "S3", "mss_final": 54.1},
    ]
    assert forecast_overrun_ceiling_lifted(scans, settings)

    evaluation = evaluate_snapshot(_snapshot(54.1), settings)
    assert evaluation["report"]["verdict"] == "观察"

    meta = apply_intraday_macro_verdict_ceiling(
        evaluation,
        scans=scans,
        lookback_mss=54.1,
        settings=settings,
    )
    assert meta.get("ceiling_lifted") is True
    assert evaluation["report"]["verdict"] == "可做"
    assert evaluation["verdict"].label_key == "buy"


@patch("agent_reach.daily_run.week_forecast.load_active_forecast", return_value=_forecast())
@patch("agent_reach.daily_run.trade_calendar.today_shanghai")
def test_lift_does_not_bypass_buy_gate(mock_today, _load_fc):
    from datetime import date

    mock_today.return_value = date(2026, 10, 29)
    settings = _gating_settings()
    settings["thresholds"]["aggressive_entry"] = 45
    scans = [
        {"scan_id": "S1", "mss_final": 54.0},
        {"scan_id": "S2", "mss_final": 54.2},
    ]
    evaluation = evaluate_snapshot(_snapshot(54.0), settings)
    apply_intraday_macro_verdict_ceiling(
        evaluation,
        scans=scans,
        lookback_mss=54.1,
        settings=settings,
    )
    verdict = evaluation["verdict"]
    assert verdict.verdict == "可做"

    decision = _decide_trade(
        lookback_mss=54.1,
        trend="flat",
        verdict=verdict,
        report={
            **evaluation["report"],
            "blocked": True,
            "audit_passed": False,
        },
        snapshot={
            "code": "688008",
            "portfolio": {"cash_ratio": 0.6, "cash": 60000, "total": 100000, "holdings": []},
        },
        settings=settings,
        trade_index=1,
        expected_return_pct=0.02,
    )
    assert decision.action != "buy"
    assert decision.blocked is True
