# -*- coding: utf-8
"""Tests for intraday rebound fast-path overlay."""

from agent_reach.daily_run.harness_policy import (
    aggressive_entry_default,
    macro_veto_default,
    threshold_default,
)
from agent_reach.daily_run.intraday import _decide_trade
from agent_reach.daily_run.intraday_policy import trend_allows_buy
from agent_reach.daily_run.intraday_rebound import (
    apply_intraday_rebound_overlay,
    detect_intraday_session_rebound,
    intraday_rebound_active,
)
from agent_reach.daily_run.lookback import detect_mss_trend
from agent_reach.daily_run.verdict import VerdictResult


def _defensive_runtime() -> dict:
    return {
        "trade_signals": {"defensive_trim": True, "mss_forecast_miss": True},
        "trend_policy": {
            "trend_min_points": 2,
            "trend_delta_threshold": 1.5,
            "buy_trends": ["rising"],
            "sell_trends": ["falling", "turning_down", "mixed", "flat"],
        },
        "deep_loss_policy": {
            "sell_ratio": 0.5,
            "non_deep_loss_sell_ratio": 0.7,
        },
        "defensive_trim_policy": {
            "defensive_trim_min_mss": 42.0,
            "defensive_trim_mss_buffer": 2.0,
        },
    }


def _rebound_scans() -> list[dict]:
    return [
        {"scan_id": "S6", "mss_final": 54.0},
        {"scan_id": "S7", "mss_final": 55.0},
        {"scan_id": "S8", "mss_final": 46.67, "source": "midday", "trend_excluded": True},
        {"scan_id": "S9", "mss_final": 48.0},
        {"scan_id": "S10", "mss_final": 52.0},
        {"scan_id": "S11", "mss_final": 55.0},
    ]


def test_detect_session_rebound_after_midday_excluded():
    settings = {
        "harness": {"enabled": True, "runtime_overlay": True},
        "intraday": {
            "trend_min_points": 2,
            "trend_delta_threshold": 1.0,
            "rebound": {"enabled": True, "min_mss_delta": 3.0, "min_latest_mss": 50.0},
        },
        "harness_runtime": _defensive_runtime(),
    }
    rebound = detect_intraday_session_rebound(_rebound_scans(), settings)
    assert rebound is not None
    assert rebound["trend"] in {"rising", "turning_up"}
    assert rebound["delta_from_low"] >= 3.0
    assert rebound["latest_scan_id"] == "S11"


def test_rebound_overlay_restores_turning_up_buy_trend():
    settings = {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45},
        "harness": {"enabled": True, "runtime_overlay": True},
        "intraday": {
            "trend_min_points": 2,
            "trend_delta_threshold": 1.0,
            "rebound": {"enabled": True},
        },
        "harness_runtime": _defensive_runtime(),
    }
    patched = apply_intraday_rebound_overlay(settings, _rebound_scans())
    assert intraday_rebound_active(patched)
    assert patched["harness_runtime"]["trade_signals"]["defensive_trim"] is False
    buy_trends = patched["harness_runtime"]["trend_policy"]["buy_trends"]
    assert "turning_up" in buy_trends
    assert patched["thresholds"]["macro_veto"] >= 38.0
    assert patched["thresholds"]["aggressive_entry"] >= 48.0


def test_rebound_unblocks_buy_at_turning_up():
    settings = {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45, "min_cash_ratio": 0.0},
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001, "holding_lock_days": 1},
        "harness": {
            "enabled": True,
            "runtime_overlay": True,
            "macro_veto_mode": "harness",
            "aggressive_entry_mode": "harness",
        },
        "intraday": {
            "trend_min_points": 2,
            "trend_delta_threshold": 1.0,
            "rebound": {"enabled": True},
        },
        "harness_runtime": _defensive_runtime(),
    }
    before = apply_intraday_rebound_overlay({**settings, "harness_runtime": _defensive_runtime()}, [])
    assert not intraday_rebound_active(before)

    patched = apply_intraday_rebound_overlay(settings, _rebound_scans())
    patched.setdefault("harness_runtime", {})["position_policy"] = {
        "deploy_ratio": 1.0,
        "max_position_pct": 35.0,
    }
    trend = detect_mss_trend(_rebound_scans(), patched)
    assert trend in {"rising", "turning_up"}
    assert trend_allows_buy(patched, trend)

    verdict = VerdictResult(
        verdict="观察",
        confidence="中",
        mss_final=55,
        entry_price=None,
        stop_loss_price=None,
        invalidation="",
        reasoning="",
        blocked=False,
    )
    decision = _decide_trade(
        lookback_mss=54.0,
        trend=trend,
        verdict=verdict,
        report={"code": "688008", "name": "澜起科技", "blocked": False, "audit_passed": True},
        snapshot={
            "code": "688008",
            "portfolio": {
                "cash_ratio": 0.6,
                "cash": 60000,
                "total": 100000,
                "holdings": [],
                "watchlist": [{"code": "688008", "name": "澜起科技"}],
            },
            "watchlist": [{"code": "688008", "price": 50.0, "name": "澜起科技"}],
            "symbols": [{"code": "688008", "price": 50.0, "name": "澜起科技"}],
        },
        settings=patched,
        trade_index=1,
        expected_return_pct=0.02,
    )
    assert decision.action == "buy"
    assert decision.blocked is False


def test_threshold_default_respects_rebound_without_reoverlay():
    settings = {
        "thresholds": {"macro_veto": 38, "aggressive_entry": 48},
        "harness": {"enabled": True, "macro_veto_mode": "harness", "aggressive_entry_mode": "harness"},
        "harness_runtime": {"intraday_rebound": {"active": True}},
    }
    assert threshold_default(settings, "macro_veto") == 38.0
    assert aggressive_entry_default(settings) == 48.0
    assert macro_veto_default(settings) == 38.0


def test_no_rebound_when_defensive_trim_absent():
    settings = {
        "intraday": {"rebound": {"enabled": True, "require_defensive_trim": True}},
        "harness_runtime": {"trade_signals": {"defensive_trim": False}},
    }
    assert detect_intraday_session_rebound(_rebound_scans(), settings) is None
