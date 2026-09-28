# -*- coding: utf-8 -*-
"""Tests for TSP (Tick-Stock-Panel) quant adapter and daily-run integration."""

import pytest
from agent_reach.daily_run.tsp.market_regime import (
    classify_tsp_market_phase,
    compute_tsp_market_phase,
    map_tsp_phase_to_session_regime,
)
from agent_reach.daily_run.tsp.deviation_monitor import (
    check_portfolio_deviation_risk,
    compute_exchange_deviation_risk,
    get_board_deviation_limit_3d,
)
from agent_reach.daily_run.tsp.mainline_ranker import (
    rank_tsp_mainlines,
    score_mainline_sector,
)
from agent_reach.daily_run.session_overlay import (
    SessionOverlayContext,
    compute_session_overlay,
    week_open_trade_block,
)
from agent_reach.daily_run.verdict import _check_tsp_deviation_filter


def test_tsp_market_phase_classification():
    # 1. Climax: Many limit ups
    assert classify_tsp_market_phase(
        limit_up_count=60,
        limit_down_count=2,
        broken_rate=0.15,
        highest_board=7,
        two_board_count=5,
    ) == "climax"

    # 2. Retreat: High broken rate
    assert classify_tsp_market_phase(
        limit_up_count=20,
        limit_down_count=18,
        broken_rate=0.40,
        highest_board=3,
        two_board_count=1,
    ) == "retreat"

    # 3. Freezing: Depressed market
    assert classify_tsp_market_phase(
        limit_up_count=10,
        limit_down_count=5,
        broken_rate=0.20,
        highest_board=2,
        two_board_count=1,
    ) == "freezing"

    # 4. Launching: Low-board expansion
    assert classify_tsp_market_phase(
        limit_up_count=28,
        limit_down_count=2,
        broken_rate=0.18,
        highest_board=4,
        two_board_count=5,
    ) == "launching"

    # 5. Main up
    assert classify_tsp_market_phase(
        limit_up_count=38,
        limit_down_count=2,
        broken_rate=0.20,
        highest_board=5,
        two_board_count=3,
    ) == "main_up"


def test_map_tsp_phase_to_session_regime():
    assert map_tsp_phase_to_session_regime("freezing") == "defensive"
    assert map_tsp_phase_to_session_regime("retreat") == "defensive"
    assert map_tsp_phase_to_session_regime("launching") == "supportive"
    assert map_tsp_phase_to_session_regime("main_up") == "supportive"
    assert map_tsp_phase_to_session_regime("climax") == "neutral"
    assert map_tsp_phase_to_session_regime("repair") == "neutral"


def test_tsp_deviation_limits_and_risk():
    # Board limit tests
    assert get_board_deviation_limit_3d("600000") == 20.0
    assert get_board_deviation_limit_3d("300750") == 30.0
    assert get_board_deviation_limit_3d("688981") == 30.0
    assert get_board_deviation_limit_3d("830941") == 40.0
    assert get_board_deviation_limit_3d("000001", name="*ST平安") == 12.0

    # Risk calculation: normal safe
    safe_row = {"code": "600000", "name": "浦发银行", "change_pct_3d": 5.0}
    risk_safe = compute_exchange_deviation_risk(safe_row)
    assert not risk_safe["warning"]
    assert not risk_safe["blocked_buy"]
    assert risk_safe["risk_level"] == "safe"

    # Risk calculation: warning (approaching 20.0 * 0.85 = 17.0)
    warn_row = {"code": "600000", "name": "浦发银行", "change_pct_3d": 17.5}
    risk_warn = compute_exchange_deviation_risk(warn_row)
    assert risk_warn["warning"]
    assert not risk_warn["blocked_buy"]
    assert risk_warn["risk_level"] == "warning"

    # Risk calculation: hard block (approaching 20.0 * 0.90 = 18.0)
    block_row = {"code": "600000", "name": "浦发银行", "change_pct_3d": 18.8}
    risk_block = compute_exchange_deviation_risk(block_row)
    assert risk_block["warning"]
    assert risk_block["blocked_buy"]
    assert risk_block["risk_level"] == "critical"


def test_check_portfolio_deviation_risk():
    holdings = [
        {"code": "600000", "name": "浦发银行", "change_pct_3d": 5.0},
        {"code": "300750", "name": "宁德时代", "change_pct_3d": 27.5},  # 27.5 / 30 = 91.6% -> blocked
    ]
    alerts = check_portfolio_deviation_risk(holdings)
    assert len(alerts) == 1
    assert alerts[0]["code"] == "300750"
    assert alerts[0]["blocked_buy"] is True


def test_mainline_ranker():
    stocks = [
        {"code": "000001", "name": "A", "industry": "算力", "change_pct": 10.0, "consecutive_limit_ups": 3},
        {"code": "000002", "name": "B", "industry": "算力", "change_pct": 10.0, "consecutive_limit_ups": 2},
        {"code": "000003", "name": "C", "industry": "低空", "change_pct": 10.0, "consecutive_limit_ups": 1},
        {"code": "000004", "name": "D", "industry": "低空", "change_pct": 10.0, "consecutive_limit_ups": 1},
    ]
    ranked = rank_tsp_mainlines(stocks, min_limit_ups=2)
    assert len(ranked) == 2
    # 算力 has 3-board and 2-board, should rank higher than 低空
    assert ranked[0]["sector"] == "算力"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_week_open_trade_block_with_tsp_deviation():
    settings = {
        "tsp_quant": {
            "enabled": True,
            "deviation_enabled": True,
            "deviation_block_buy_ratio": 0.90,
        }
    }
    # Normal stock shouldn't be blocked
    block_msg = week_open_trade_block(settings, "600000", "buy")
    assert block_msg is None

    # Sell should never be blocked by TSP deviation
    assert week_open_trade_block(settings, "600000", "sell") is None


def test_verdict_filter_with_tsp_deviation():
    settings = {
        "tsp_quant": {
            "enabled": True,
            "deviation_enabled": True,
            "deviation_block_buy_ratio": 0.90,
        }
    }
    snap_critical = {"code": "600000", "change_pct_3d": 19.5}  # 19.5 / 20 = 97.5% > 90%
    blocked, notes = _check_tsp_deviation_filter(snap_critical, settings)
    assert blocked is True
    assert len(notes) == 1
    assert "TSP 交易所异动偏离监管风控" in notes[0]

    snap_safe = {"code": "600000", "change_pct_3d": 5.0}
    blocked_safe, notes_safe = _check_tsp_deviation_filter(snap_safe, settings)
    assert blocked_safe is False
    assert len(notes_safe) == 0
