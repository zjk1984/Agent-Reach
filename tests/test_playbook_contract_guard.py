# -*- coding: utf-8
"""Tests for playbook contract guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_reach.daily_run.playbook_contract_guard import (
    playbook_contract_buy_block,
    playbook_contract_sell_block,
    resolve_symbol_contract,
    stock_weight_pct,
)


@pytest.fixture
def playbook_settings():
    return {
        "playbook_contract": {
            "enabled": True,
            "require_morning_handoff": True,
            "total_stock_weight_cap_pct": 37.0,
            "target_tolerance_pp": 2.0,
            "watchlist_buy_codes": ["603986"],
            "hard_stop_prices": {"002583": 8.0},
            "symbols": {
                "688008": {"block_add": True, "target_weight_pct": 19.0},
                "002583": {"min_weight_pct": 7.0, "target_weight_pct": 10.0},
                "002415": {"block_add": True, "max_weight_pct": 13.0, "target_weight_pct": 13.0},
            },
        },
        "trading": {"commission_rate": 0.0015},
        "position": {"deploy_ratio": 0.25, "max_position_pct": 25.0},
    }


@pytest.fixture
def morning_handoff(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REACH_PLAYBOOK_USE_HANDOFF", "1")
    payload = {
        "morning_date": "2026-09-22",
        "action_checklist": [
            {
                "code": "002415",
                "name": "海康威视",
                "operation": "持有",
                "target_weight_pct": 13.0,
                "current_weight_pct": 12.6,
            },
            {
                "code": "688008",
                "name": "澜起科技",
                "operation": "观望",
                "target_weight_pct": 20.0,
                "current_weight_pct": 20.3,
            },
        ],
    }
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    path = handoff_dir / "morning_2026-09-22.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    last = handoff_dir / "last_morning_handoff.json"
    last.write_text(json.dumps(payload), encoding="utf-8")

    import agent_reach.daily_run.close_morning_handoff as cmh

    monkeypatch.setattr(cmh, "_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: __import__("datetime").date(2026, 9, 22),
    )
    return payload


def test_inactive_without_morning_handoff(playbook_settings):
    portfolio = {
        "total": 103_000,
        "cash": 57_000,
        "holdings": [{"code": "002415", "shares": 400, "price": 32.58}],
    }
    block = playbook_contract_buy_block(
        settings=playbook_settings,
        portfolio=portfolio,
        snapshot={"code": "002415", "price": 33.23},
        code="002415",
    )
    assert block is None


def test_resolve_symbol_contract_merges_handoff(playbook_settings, morning_handoff):
    row = resolve_symbol_contract("002415", settings=playbook_settings)
    assert row["operation"] == "持有"
    assert row["block_add"] is True
    assert row["target_weight_pct"] == 13.0


def test_buy_blocked_for_hold_operation(playbook_settings, morning_handoff):
    portfolio = {
        "total": 103_000,
        "cash": 57_000,
        "holdings": [
            {"code": "002415", "name": "海康", "shares": 400, "price": 32.58, "cost": 32.57},
            {"code": "688008", "name": "澜起", "shares": 100, "price": 210.0, "cost": 255.87},
        ],
    }
    snapshot = {"code": "002415", "name": "海康威视", "price": 33.23}
    block = playbook_contract_buy_block(
        settings=playbook_settings,
        portfolio=portfolio,
        snapshot=snapshot,
        code="002415",
    )
    assert block is not None
    assert block.block_kind == "playbook_no_add"


def test_sell_blocked_below_playbook_floor(playbook_settings):
    portfolio = {
        "total": 104_000,
        "cash": 50_000,
        "holdings": [
            {"code": "002583", "name": "海能达", "shares": 1200, "price": 8.17, "cost": 12.618},
        ],
    }
    snapshot = {"code": "002583", "price": 8.17}
    block = playbook_contract_sell_block(
        settings=playbook_settings,
        portfolio=portfolio,
        snapshot=snapshot,
        code="002583",
        sell_shares=400,
        sell_kind="defensive_trim",
        price=8.17,
    )
    assert block is not None
    assert block.block_kind == "playbook_weight_floor"


def test_sell_allowed_at_hard_stop(playbook_settings):
    portfolio = {
        "total": 104_000,
        "cash": 50_000,
        "holdings": [
            {"code": "002583", "name": "海能达", "shares": 1200, "price": 7.95, "cost": 12.618},
        ],
    }
    block = playbook_contract_sell_block(
        settings=playbook_settings,
        portfolio=portfolio,
        snapshot={"code": "002583", "price": 7.95},
        code="002583",
        sell_shares=400,
        sell_kind="defensive_trim",
        price=7.95,
    )
    assert block is None


def test_weight_ceiling_blocks_over_target(playbook_settings, morning_handoff):
    playbook_settings["playbook_contract"]["symbols"]["002415"]["block_add"] = False
    playbook_settings["position"] = {"deploy_ratio": 0.25, "max_position_pct": 50.0}
    playbook_settings["trading"] = {"commission_rate": 0.0015, "min_cash_ratio": 0.0}
    portfolio = {
        "total": 103_000,
        "cash": 57_000,
        "holdings": [
            {"code": "002415", "name": "海康", "shares": 400, "price": 32.58, "cost": 32.57},
        ],
    }
    snapshot = {"code": "002415", "name": "海康威视", "price": 33.23}
    block = playbook_contract_buy_block(
        settings=playbook_settings,
        portfolio=portfolio,
        snapshot=snapshot,
        code="002415",
    )
    assert block is not None
    assert block.block_kind == "playbook_weight_ceiling"


def test_total_cap_blocks_when_stock_weight_high(playbook_settings):
    from agent_reach.daily_run.playbook_contract_guard import _project_stock_weight_after_buy

    current = stock_weight_pct(
        {
            "total": 100_000,
            "cash": 40_000,
            "holdings": [{"code": "688008", "shares": 100, "price": 220.0}],
        }
    )
    assert current > 20.0
    post = _project_stock_weight_after_buy(
        {"total": 100_000, "cash": 40_000, "holdings": [{"code": "688008", "shares": 100, "price": 220.0}]},
        code="688008",
        price=220.0,
        buy_shares=100,
        buy_notional=22_000.0,
    )
    assert post is not None and post > playbook_settings["playbook_contract"]["total_stock_weight_cap_pct"]
