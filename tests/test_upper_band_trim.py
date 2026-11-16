# -*- coding: utf-8 -*-
"""Upper-band / divergence-day partial trim guard."""

from __future__ import annotations

from datetime import date

import pytest

from agent_reach.daily_run.intraday import TradeDecision, _decide_trade
from agent_reach.daily_run.upper_band_trim import (
    evaluate_upper_band_trim_sell,
    next_session_kronos_divergence_day,
    resolve_upper_band_trim_triggers,
    symbol_week_price_upper,
)
from agent_reach.daily_run.verdict import VerdictResult


def _forecast_600498():
    return {
        "week_start": "2026-11-10",
        "trading_days": ["2026-11-14", "2026-11-17", "2026-11-18"],
        "structured_predictions": {
            "symbols": [
                {
                    "code": "600498",
                    "name": "烽火通信",
                    "base_price": 26.0,
                    "price_low": 24.5,
                    "price_high": 27.0,
                }
            ]
        },
        "symbols": {
            "600498": {
                "name": "烽火通信",
                "base_price": 26.0,
                "kronos_divergence_days": ["2026-11-17"],
                "days": {
                    "2026-11-14": {"change_pct_range": [0.0, 2.8]},
                },
            }
        },
        "mss_daily": {
            "2026-11-14": {"range": [48.0, 56.0]},
        },
    }


def _settings(**overrides):
    settings = {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45, "min_cash_ratio": 0.5},
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001, "holding_lock_days": 1},
        "intraday": {
            "profit_lock": {"enabled": False},
            "defensive_trim": {"enabled": False},
            "upper_band_trim": {
                "enabled": True,
                "near_upper_band_pct": 1.0,
                "sell_ratio": 0.25,
                "max_sell_ratio": 0.33,
            },
        },
        "harness_runtime": {
            "deep_loss_policy": {
                "loss_cny_threshold": 5000,
                "loss_pct_threshold": 10,
                "cover_ratio": 0.0,
                "sell_ratio": 0.5,
                "non_deep_loss_sell_ratio": 0.7,
            },
        },
        "portfolio": {"auto_adjust_enabled": True},
        "pnl_overview": {"defensive_trim_exempt_cover": True},
    }
    settings.update(overrides)
    return settings


def _fenghuo_snapshot():
    return {
        "code": "600498",
        "name": "烽火通信",
        "price": 26.87,
        "change_pct": 2.64,
        "portfolio": {
            "cash_ratio": 0.4,
            "total": 500000,
            "cash": 200000,
            "holdings": [
                {
                    "code": "600498",
                    "name": "烽火通信",
                    "shares": 1200,
                    "cost": 24.0,
                    "price": 26.87,
                    "change_pct": 2.64,
                    "days_held": 8,
                }
            ],
        },
        "symbols": [{"code": "600498", "price": 26.87, "change_pct": 2.64}],
    }


def test_symbol_week_price_upper_from_structured():
    assert symbol_week_price_upper("600498", _forecast_600498()) == 27.0


def test_triggers_fenghuo_near_upper_price(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_forecast.load_active_forecast",
        lambda *a, **k: _forecast_600498(),
    )
    triggers = resolve_upper_band_trim_triggers(
        _settings(),
        code="600498",
        price=26.87,
        change_pct=2.64,
        lookback_mss=52.0,
        forecast=_forecast_600498(),
    )
    assert any("周预测上沿" in t for t in triggers)


def test_evaluate_upper_band_trim_fenghuo_case(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_forecast.load_active_forecast",
        lambda *a, **k: _forecast_600498(),
    )
    allow, reason, ratio = evaluate_upper_band_trim_sell(
        _settings(),
        report={"code": "600498", "name": "烽火通信", "price": 26.87},
        snapshot=_fenghuo_snapshot(),
        lookback_mss=52.0,
    )
    assert allow is True
    assert reason and "预测上沿" in reason
    assert ratio == 0.25


def test_disabled_by_default_repo_settings():
    from agent_reach.daily_run.settings import load_settings

    cfg = load_settings()
    block = (cfg.get("intraday") or {}).get("upper_band_trim") or {}
    assert block.get("enabled") is False


def test_next_session_divergence_day(monkeypatch):
    fc = _forecast_600498()
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 11, 14),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.next_trading_day",
        lambda d, **k: date(2026, 11, 17),
    )
    assert next_session_kronos_divergence_day("600498", forecast=fc) is True


def test_decide_trade_sells_upper_band_trim(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_forecast.load_active_forecast",
        lambda *a, **k: _forecast_600498(),
    )
    verdict = VerdictResult(
        verdict="观察",
        confidence="中",
        mss_final=51,
        entry_price=None,
        stop_loss_price=None,
        invalidation="",
        reasoning="",
        blocked=False,
    )
    decision = _decide_trade(
        lookback_mss=52.0,
        trend="mixed",
        verdict=verdict,
        report={"code": "600498", "name": "烽火通信", "price": 26.87, "blocked": False},
        snapshot=_fenghuo_snapshot(),
        settings=_settings(),
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
        session_scans=[],
    )
    assert isinstance(decision, TradeDecision)
    assert decision.action == "sell"
    assert decision.sell_kind == "upper_band_trim"
    assert decision.sell_ratio_override == 0.25


def test_once_per_day_blocks_repeat():
    allow, reason, _ = evaluate_upper_band_trim_sell(
        _settings(),
        report={"code": "600498"},
        snapshot=_fenghuo_snapshot(),
        lookback_mss=52.0,
        prior_trades=[
            {
                "action": "sell",
                "code": "600498",
                "portfolio_applied": True,
                "sell_kind": "upper_band_trim",
            }
        ],
    )
    assert allow is False
    assert "今日已执行" in (reason or "")


@pytest.mark.parametrize(
    "price,change,expect",
    [
        (25.0, 0.5, False),
        (26.87, 2.64, True),
    ],
)
def test_triggers_only_near_band(price, change, expect, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_forecast.load_active_forecast",
        lambda *a, **k: _forecast_600498(),
    )
    settings = _settings()
    settings["intraday"]["upper_band_trim"]["trigger_on_next_kronos_divergence_day"] = False
    triggers = resolve_upper_band_trim_triggers(
        settings,
        code="600498",
        price=price,
        change_pct=change,
        lookback_mss=45.0,
        forecast=_forecast_600498(),
    )
    assert bool(triggers) is expect