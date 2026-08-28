# -*- coding: utf-8 -*-
"""Tests for intraday profit-lock (dynamic take-profit)."""

from agent_reach.daily_run.intraday import TradeDecision, _decide_trade
from agent_reach.daily_run.portfolio_manager import apply_auto_adjust, deep_loss_sell_analysis
from agent_reach.daily_run.profit_lock import evaluate_profit_lock_sell
from agent_reach.daily_run.verdict import VerdictResult


def _base_settings(**overrides):
    settings = {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45, "min_cash_ratio": 0.5},
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001, "holding_lock_days": 1},
        "intraday": {
            "profit_lock": {
                "enabled": True,
                "min_intraday_gain_pct": 4.0,
                "min_position_20d": 0.70,
                "min_unrealized_gain_pct": 3.0,
                "sell_ratio": 0.30,
                "trigger_mode": "threshold",
            },
            "defensive_trim": {"enabled": False},
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
    }
    settings.update(overrides)
    return settings


def _holding_snapshot(**holding_overrides):
    holding = {
        "code": "300308",
        "name": "中际旭创",
        "shares": 300,
        "cost": 820.0,
        "price": 915.88,
        "change_pct": 5.74,
        "position_20d": 0.92,
        "days_held": 5,
    }
    holding.update(holding_overrides)
    return {
        "code": "300308",
        "name": "中际旭创",
        "price": holding["price"],
        "change_pct": holding["change_pct"],
        "position_20d": holding["position_20d"],
        "portfolio": {"cash_ratio": 0.4, "total": 500000, "cash": 200000, "holdings": [holding]},
        "symbols": [{"code": "300308", "price": holding["price"], "change_pct": holding["change_pct"]}],
    }


def test_profit_lock_triggers_on_intraday_high():
    allow, reason, ratio = evaluate_profit_lock_sell(
        _base_settings(),
        report={"code": "300308", "name": "中际旭创"},
        snapshot=_holding_snapshot(),
    )
    assert allow is True
    assert reason is not None
    assert "动态止盈" in reason
    assert ratio == 0.30


def test_profit_lock_skips_watchlist_only():
    allow, reason, ratio = evaluate_profit_lock_sell(
        _base_settings(),
        report={"code": "300308", "name": "中际旭创"},
        snapshot={
            "code": "300308",
            "change_pct": 5.74,
            "position_20d": 0.92,
            "portfolio": {
                "watchlist": [{"code": "300308", "name": "中际旭创"}],
                "holdings": [],
            },
        },
    )
    assert allow is False
    assert reason is None
    assert ratio is None


def test_decide_trade_sells_on_profit_lock():
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
        lookback_mss=51.0,
        trend="mixed",
        verdict=verdict,
        report={"code": "300308", "name": "中际旭创", "blocked": False},
        snapshot=_holding_snapshot(),
        settings=_base_settings(),
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
    )
    assert decision.action == "sell"
    assert decision.sell_kind == "profit_lock"
    assert decision.sell_ratio_override == 0.30
    assert "动态止盈" in decision.reasoning


def test_profit_lock_once_per_day_blocks_repeat():
    allow, reason, _ = evaluate_profit_lock_sell(
        _base_settings(),
        report={"code": "300308"},
        snapshot=_holding_snapshot(),
        prior_trades=[
            {
                "action": "sell",
                "code": "300308",
                "portfolio_applied": True,
                "sell_kind": "profit_lock",
                "reasoning": "动态止盈",
            }
        ],
    )
    assert allow is False
    assert reason is not None
    assert "不再重复" in reason


def test_decide_trade_profit_lock_before_defensive_trim():
    settings = _base_settings(
        intraday={
            "profit_lock": {
                "enabled": True,
                "min_intraday_gain_pct": 4.0,
                "min_position_20d": 0.70,
                "min_unrealized_gain_pct": 3.0,
                "sell_ratio": 0.30,
            },
            "defensive_trim": {"enabled": True, "max_symbol_change_pct": 1.0},
        },
        harness_runtime={
            "trade_signals": {"defensive_trim": True, "mss_forecast_miss": True},
            "deep_loss_policy": {
                "loss_cny_threshold": 5000,
                "loss_pct_threshold": 10,
                "cover_ratio": 0.0,
                "sell_ratio": 0.5,
                "non_deep_loss_sell_ratio": 0.7,
            },
            "trend_policy": {"sell_trends": ["falling", "turning_down", "mixed"]},
        },
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
        lookback_mss=51.0,
        trend="mixed",
        verdict=verdict,
        report={"code": "300308", "name": "中际旭创", "blocked": False},
        snapshot=_holding_snapshot(change_pct=5.74),
        settings=settings,
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
    )
    assert decision.action == "sell"
    assert decision.sell_kind == "profit_lock"


def test_apply_sell_uses_profit_lock_ratio():
    settings = _base_settings()
    snapshot = _holding_snapshot()
    pf = snapshot["portfolio"]
    enriched = {"300308": {"price": 915.88, "change_pct": 5.74}}
    decision = TradeDecision(
        action="sell",
        trade_id="T1",
        lookback_mss=51.0,
        lookback_detail=[],
        trend="mixed",
        reasoning="动态止盈",
        sell_kind="profit_lock",
        sell_ratio_override=0.30,
    )
    analysis = deep_loss_sell_analysis(pf, pf["holdings"][0], enriched, settings)
    assert analysis["allowed"] is True

    result = apply_auto_adjust(pf, decision, snapshot, settings)
    assert result.applied is True
    assert result.actions[0].shares == 100
