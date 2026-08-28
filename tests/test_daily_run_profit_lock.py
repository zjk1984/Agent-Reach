# -*- coding: utf-8 -*-
"""Tests for intraday profit-lock (dynamic take-profit)."""

import pytest

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
    enriched = {"300308": {"price": 915.88, "change_pct": 5.74}}
    analysis = deep_loss_sell_analysis(pf, pf["holdings"][0], enriched, settings)
    assert analysis["allowed"] is True

    result = apply_auto_adjust(pf, decision, snapshot, settings)
    assert result.applied is True
    assert result.actions[0].shares == 100


def test_profit_lock_harness_evolve_on_take_profit_reference():
    from agent_reach.daily_run.harness import HarnessEntry, HarnessState
    from agent_reach.daily_run.harness_policy import resolve_harness_profit_lock_policy

    state = HarnessState()
    state.entries["playbook"]["tp"] = HarnessEntry(
        id="tp",
        kind="playbook",
        title="止盈参考",
        content="止盈参考：中际旭创 已实现 +800，同类标的可分批兑现",
        source="deterministic",
        job="close",
        evidence="close",
        created_at="2026-08-28T00:00:00+00:00",
        updated_at="2026-08-28T00:00:00+00:00",
    )
    settings = {
        "harness": {"runtime_overlay_sources": ["playbook"]},
        "intraday": {
            "profit_lock": {
                "min_intraday_gain_pct": 4.0,
                "min_position_20d": 0.70,
                "min_unrealized_gain_pct": 3.0,
                "sell_ratio": 0.30,
                "pullback_from_high_pct": 1.5,
            }
        },
    }
    policy = resolve_harness_profit_lock_policy(state, settings=settings)
    assert policy["min_intraday_gain_pct"] == 3.5
    assert policy["min_position_20d"] == pytest.approx(0.67, abs=0.001)
    assert policy["sell_ratio"] == 0.35


def test_profit_lock_harness_evolve_on_sell_late_phrase():
    from agent_reach.daily_run.harness import HarnessEntry, HarnessState
    from agent_reach.daily_run.harness_policy import resolve_harness_profit_lock_policy

    state = HarnessState()
    state.entries["memory"]["late"] = HarnessEntry(
        id="late",
        kind="memory",
        title="卖晚了",
        content="中际旭创高位 +5.7% 未减仓，卖晚了",
        source="deterministic",
        job="intraday",
        evidence="intraday",
        created_at="2026-08-28T00:00:00+00:00",
        updated_at="2026-08-28T00:00:00+00:00",
    )
    settings = {"harness": {"runtime_overlay_sources": ["memory"]}}
    policy = resolve_harness_profit_lock_policy(state, settings=settings)
    assert policy["min_intraday_gain_pct"] == 3.0
    assert policy["sell_ratio"] == 0.40


def test_profit_lock_harness_miss_on_holding():
    from agent_reach.daily_run.profit_lock import profit_lock_harness_evidence

    settings = {
        "intraday": {
            "profit_lock": {
                "enabled": True,
                "min_intraday_gain_pct": 4.0,
                "min_position_20d": 0.70,
                "min_unrealized_gain_pct": 3.0,
                "sell_ratio": 0.30,
            }
        }
    }
    lines = profit_lock_harness_evidence(
        settings,
        code="300308",
        name="中际旭创",
        scan_id="S5",
        snapshot={
            "code": "300308",
            "price": 915.88,
            "change_pct": 5.74,
            "position_20d": 0.92,
            "portfolio": {
                "holdings": [
                    {
                        "code": "300308",
                        "shares": 300,
                        "cost": 820.0,
                        "price": 915.88,
                        "change_pct": 5.74,
                        "position_20d": 0.92,
                    }
                ]
            },
        },
        decision={"action": "hold", "trend": "mixed", "reasoning": "维持观望"},
        prior_trades=[],
        session_scans=[{"scan_id": "S4", "code": "300308", "price": 896.74}],
    )
    assert any("卖晚了" in item for item in lines["memory"])
    assert any("profit_lock" in item for item in lines["policy"])


def test_profit_lock_harness_watchlist_high_position():
    from agent_reach.daily_run.profit_lock import profit_lock_harness_evidence

    settings = {"intraday": {"profit_lock": {"enabled": True}}}
    lines = profit_lock_harness_evidence(
        settings,
        code="300308",
        name="中际旭创",
        scan_id="S5",
        snapshot={
            "code": "300308",
            "change_pct": 5.74,
            "position_20d": 0.92,
            "portfolio": {"watchlist": [{"code": "300308"}], "holdings": []},
        },
    )
    assert any("观察池高位" in item for item in lines["playbook"])


def test_intraday_harness_writes_sell_late_memory():
    from agent_reach.daily_run.intraday_harness import intraday_to_harness_evidence

    ev = intraday_to_harness_evidence(
        {
            "scan": {
                "scan": {
                    "scan_id": "S5",
                    "code": "300308",
                    "name": "中际旭创",
                    "mss_final": 51.0,
                },
                "enriched": {
                    "code": "300308",
                    "name": "中际旭创",
                    "price": 915.88,
                    "change_pct": 5.74,
                    "position_20d": 0.92,
                    "portfolio": {
                        "holdings": [
                            {
                                "code": "300308",
                                "shares": 300,
                                "cost": 820.0,
                                "price": 915.88,
                                "change_pct": 5.74,
                                "position_20d": 0.92,
                            }
                        ]
                    },
                },
                "state": {"scans": [{"scan_id": "S4", "code": "300308", "price": 896.74}], "trades": []},
            },
            "trade": {
                "decision": {
                    "action": "hold",
                    "trend": "mixed",
                    "reasoning": "Lookback MSS 51，趋势 mixed，维持观望",
                }
            },
        },
        settings={"intraday": {"profit_lock": {"enabled": True}}},
    )
    assert any("卖晚了" in item for item in ev["memory"])
    assert any("profit_lock" in item for item in ev["policy"])
