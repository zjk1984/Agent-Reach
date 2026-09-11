# -*- coding: utf-8
"""Tests for Freqtrade-inspired intraday protections + hyperopt-lite + lookahead audit."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from agent_reach.daily_run.hyperopt_lite import run_hyperopt_lite
from agent_reach.daily_run.lookahead_audit import audit_snapshot_lookahead
from agent_reach.daily_run.protections.engine import protection_block_reason
from agent_reach.daily_run.protections.max_drawdown_guard import evaluate_max_drawdown_guard
from agent_reach.daily_run.protections.post_sell_cooldown import evaluate_post_sell_cooldown
from agent_reach.daily_run.protections.sector_mss_mismatch import (
    detect_sector_mss_mismatch,
    protection_verdict_cap,
)

_SH = ZoneInfo("Asia/Shanghai")


def _protection_settings(**overrides) -> dict:
    base = {
        "protections": {
            "enabled": True,
            "post_sell_cooldown": {
                "enabled": True,
                "min_scans_after_sell": 2,
                "block_before_hour": 14,
            },
            "sector_mss_mismatch": {
                "enabled": True,
                "min_mss": 49.0,
                "min_underperform_index_pct": 1.5,
                "sectors": ["AI算力", "半导体"],
                "verdict_cap": "观察",
            },
            "max_drawdown": {
                "enabled": True,
                "max_losing_streak": 3,
                "lookback_trades": 8,
                "stop_duration_scans": 3,
            },
        }
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            block = dict(base[key])
            block.update(value)
            base[key] = block
        else:
            base[key] = value
    return base


def test_post_sell_cooldown_blocks_repeat_trade_on_000725():
    prior = [
        {"trade_id": "T1", "code": "000725", "action": "sell", "portfolio_applied": True},
        {"trade_id": "T2", "code": "000725", "action": "hold", "portfolio_applied": True},
    ]
    settings = _protection_settings()
    now = datetime(2026, 9, 10, 10, 30, tzinfo=_SH)

    buy_lock = evaluate_post_sell_cooldown(
        code="000725",
        name="京东方A",
        side="buy",
        settings=settings,
        prior_trades=prior,
        now=now,
    )
    sell_lock = evaluate_post_sell_cooldown(
        code="000725",
        name="京东方A",
        side="sell",
        settings=settings,
        prior_trades=prior,
        now=now,
    )

    assert buy_lock is not None and buy_lock.lock is True
    assert buy_lock.protection == "post_sell_cooldown"
    assert sell_lock is not None and sell_lock.lock is True
    assert "post_sell_cooldown" in sell_lock.reason


def test_sector_mss_mismatch_detects_601138_style_underperform():
    snapshot = {
        "macro_ctx": {
            "indices": {"sh000300": {"change_pct": -0.5}},
        },
        "symbols": [
            {
                "code": "601138",
                "name": "工业富联",
                "sector": "AI算力",
                "change_pct": -3.2,
            }
        ],
    }
    report = {"code": "601138", "name": "工业富联", "mss_final": 52.0, "verdict": "可做"}
    settings = _protection_settings()

    hit = detect_sector_mss_mismatch(snapshot=snapshot, report=report, settings=settings)
    assert hit is not None
    assert hit["underperform_pct"] >= 1.5

    cap = protection_verdict_cap(snapshot=snapshot, report=report, settings=settings)
    assert cap == "观察"

    block = protection_block_reason(
        snapshot=snapshot,
        report=report,
        side="buy",
        settings=settings,
    )
    assert block is not None
    assert block.protection == "sector_mss_mismatch"


def test_max_drawdown_guard_blocks_global_buy_after_losing_streak():
    prior = [
        {"trade_id": "T1", "code": "600000", "action": "sell", "portfolio_applied": True, "realized_pnl": -120.0},
        {"trade_id": "T2", "code": "600001", "action": "sell", "portfolio_applied": True, "realized_pnl": -80.0},
        {"trade_id": "T3", "code": "600002", "action": "sell", "portfolio_applied": True, "realized_pnl": -50.0},
    ]
    settings = _protection_settings()

    lock = evaluate_max_drawdown_guard(side="buy", settings=settings, prior_trades=prior)
    assert lock is not None
    assert lock.scope == "global"
    assert lock.protection == "max_drawdown_guard"


def test_hyperopt_lite_grid_search_returns_optimal_params():
    report = {
        "weekly_pnl_pct": -1.2,
        "sell_rules_whatif": {
            "baseline_realized_pnl": 100.0,
            "evolved_realized_pnl": 140.0,
        },
    }
    result = run_hyperopt_lite(
        report,
        settings={"hyperopt_lite": {"enabled": True, "trials": 8, "prefer_optuna": False}},
    )
    assert result.get("skipped") is False
    assert result.get("planner") == "grid"
    optimal = result.get("optimal") or {}
    assert "deploy_ratio" in optimal
    assert "sector_gap_min_fade_pct" in optimal
    assert "sector_gap_macro_veto_bump" in optimal


def test_lookahead_audit_flags_future_macro_timestamp():
    snapshot = {
        "as_of": "2026-09-10T10:00:00+08:00",
        "report_type": "intraday",
        "macro_ctx": {"as_of": "2026-09-10T11:00:00+08:00"},
    }
    result = audit_snapshot_lookahead(snapshot, job="intraday")
    assert result["ok"] is False
    assert any("macro_ctx" in item for item in result["findings"])
