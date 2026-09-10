# -*- coding: utf-8
"""Tests for learn_backtrader P0/P1 patterns."""

from agent_reach.daily_run.bar_alignment import annotate_enriched_bar_quality, assess_symbol_bar_quality
from agent_reach.daily_run.execution_sim import (
    apply_slippage,
    cap_shares_by_bar_volume,
    resolve_fill_timing,
    sim_execution_price,
)
from agent_reach.daily_run.indicator_warmup import indicator_warmup_block_reason
from agent_reach.daily_run.order_state import classify_reject_reason, order_state_for_apply
from agent_reach.daily_run.signal_events import build_signal_event
from agent_reach.daily_run.strategy_analyzers import analyze_equity_curve, build_strategy_analyzers
from agent_reach.daily_run.sell_rules_whatif import _annotate_sell_whatif_oco


def test_apply_slippage_buy_vs_sell():
    base = 10.0
    buy = apply_slippage(base, side="buy", slippage_rate=0.001)
    sell = apply_slippage(base, side="sell", slippage_rate=0.001)
    assert buy > base
    assert sell < base


def test_cap_shares_by_bar_volume():
    shares, capped = cap_shares_by_bar_volume(
        5000,
        {"volume": 10000},
        settings={"execution_sim": {"max_bar_participation_pct": 10}},
    )
    assert shares == 1000
    assert capped is True


def test_sim_execution_price_close_default():
    price, meta = sim_execution_price(
        {"code": "688008", "price": 50.0},
        {"688008": {"price": 50.0}},
        side="buy",
        settings={"execution_sim": {"enabled": True, "fill_timing": "close"}},
    )
    assert price is not None
    assert meta["fill_timing"] == "close"


def test_sim_execution_price_next_open():
    price, meta = sim_execution_price(
        {"code": "688008", "open": 49.5, "price": 50.0},
        {"688008": {"open": 49.5, "price": 50.0}},
        side="buy",
        settings={"execution_sim": {"enabled": True, "fill_timing": "next_open", "apply_slippage_live": False}},
    )
    assert price == 49.5
    assert meta["price_source"] == "open"


def test_order_state_classify():
    assert classify_reject_reason("现金不足") == "margin"
    assert order_state_for_apply(applied=True) == "complete"
    assert order_state_for_apply(applied=False, message="T+1 锁仓") == "rejected"


def test_indicator_warmup_blocks():
    reason = indicator_warmup_block_reason(
        {"mss_history": [{"mss": 40}]},
        settings={"indicator_warmup": {"enabled": True, "min_mss_history_points": 3}},
    )
    assert reason and "预热" in reason


def test_signal_event_build():
    event = build_signal_event(
        {"code": "688008", "name": "澜起", "verdict": "观察", "mss_final": 42},
        {"action": "buy", "blocked": False, "friction_blocked": True, "reasoning": "摩擦阻断"},
    )
    assert event["signal"] == "buy"
    assert event["friction_blocked"] is True


def test_strategy_analyzers_drawdown():
    analyzers = build_strategy_analyzers(
        daily_totals=[
            {"date": "2026-09-08", "total": 100000},
            {"date": "2026-09-09", "total": 95000},
            {"date": "2026-09-10", "total": 98000},
        ],
        trade_pnl_detail={"sells": [{"realized_pnl": 100}, {"realized_pnl": -50}]},
    )
    assert analyzers["equity"]["max_drawdown_pct"] >= 5.0
    assert analyzers["trades"]["profit_factor"] == 2.0


def test_sell_whatif_oco_annotation():
    rows = _annotate_sell_whatif_oco(
        [{"code": "688008", "is_deep_loss": True, "sell_ratio": 0.5, "actual_sold": 100}]
    )
    assert rows[0]["oco_group_id"] == "deep_loss_partial_oco"


def test_bar_quality_annotation():
    enriched = annotate_enriched_bar_quality(
        {"688008": {"price": 10.0, "volume": 0}},
        settings={"bar_alignment": {"enabled": True}},
    )
    assert enriched["688008"]["bar_quality"] == "stale_volume"
    assert assess_symbol_bar_quality({"price": 10.0}) == "missing_volume"
