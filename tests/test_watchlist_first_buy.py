# -*- coding: utf-8
"""Watchlist first-buy sizing and playbook total-cap interaction."""

from __future__ import annotations

from agent_reach.daily_run.playbook_contract_guard import playbook_contract_buy_block
from agent_reach.daily_run.portfolio_manager import simulate_buy_analysis


def _portfolio():
    return {
        "total": 102_094.84,
        "cash": 78_534.84,
        "holdings": [
            {"code": "002583", "name": "海能达", "shares": 400, "cost": 12.6, "price": 8.07},
            {"code": "000725", "name": "京东方A", "shares": 200, "cost": 5.95, "price": 5.71},
            {"code": "002415", "name": "海康威视", "shares": 600, "cost": 32.9, "price": 32.11},
        ],
        "watchlist": [{"code": "002236", "name": "大华股份", "price": 15.32}],
    }


def test_watchlist_first_buy_caps_shares_under_total_cap():
    settings = {
        "playbook_contract": {
            "enabled": True,
            "total_stock_weight_cap_pct": 37.0,
            "watchlist_first_buy_enabled": True,
            "watchlist_first_buy_pct": 3.0,
        },
        "trading": {"commission_rate": 0.0015},
        "thresholds": {"min_cash_ratio": 0.1, "aggressive_entry": 45, "macro_veto": 30},
    }
    pf = _portfolio()
    enriched = {
        "002236": {"code": "002236", "name": "大华股份", "price": 15.32, "change_pct": 0.59},
    }
    analysis = simulate_buy_analysis(
        pf,
        enriched,
        settings,
        prefer_code="002236",
    )
    assert analysis["allowed"] is True
    shares = int(analysis["buy_shares"])
    assert shares > 0
    notional = shares * 15.32
    assert notional <= pf["total"] * 0.03 + 20.0

    block = playbook_contract_buy_block(
        settings=settings,
        portfolio=pf,
        snapshot={"watchlist": pf["watchlist"]},
        enriched=enriched,
        code="002236",
    )
    assert block is None
