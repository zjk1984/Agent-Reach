# -*- coding: utf-8
"""Tests for memory-driven defensive trim guards."""

import json
from pathlib import Path

from agent_reach.daily_run.defensive_trim_guards import (
    defensive_trim_blocked_by_recovery_zone,
    defensive_trim_blocked_by_strength,
    evaluate_defensive_trim_sell,
    mixed_early_mss_recovery,
)
from agent_reach.daily_run.harness import HarnessEntry, HarnessState
from agent_reach.daily_run.harness_policy import resolve_harness_trade_signals
from agent_reach.daily_run.harness_reading_signals import resolve_harness_reading_signals
from agent_reach.daily_run.intraday import _decide_trade
from agent_reach.daily_run.portfolio_manager import deep_loss_sell_analysis
from agent_reach.daily_run.verdict import VerdictResult


def _write_intraday_state(tmp_path: Path, scans: list[dict]) -> None:
    state_path = tmp_path / "intraday_state.json"
    state_path.write_text(
        json.dumps({"date": "2026-08-27", "scans": scans, "trades": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_recovery_zone_blocks_memory_trim_at_high_lookback():
    reason = defensive_trim_blocked_by_recovery_zone(
        {"harness": {"reading_signals": {"recovery_min_lookback": 52.0, "recovery_macro_veto": 38.0}}},
        lookback_mss=51.0,
        trade_signals={"defensive_trim": True, "mss_forecast_miss": True},
    )
    assert reason is None

    reason = defensive_trim_blocked_by_recovery_zone(
        {"harness": {"reading_signals": {"recovery_min_lookback": 52.0, "recovery_macro_veto": 38.0}}},
        lookback_mss=52.0,
        trade_signals={"defensive_trim": True, "mss_forecast_miss": True},
    )
    assert reason is not None
    assert "回暖线" in reason


def test_pnl_miss_bypasses_recovery_zone_block():
    reason = defensive_trim_blocked_by_recovery_zone(
        {"harness": {"reading_signals": {"recovery_min_lookback": 52.0}}},
        lookback_mss=55.0,
        trade_signals={"defensive_trim": True, "pnl_target_miss": True},
    )
    assert reason is None


def test_mixed_early_recovery_at_lookback_51(tmp_path, monkeypatch):
    scans = [
        {"scan_id": "S6", "mss_final": 48.0},
        {"scan_id": "S7", "mss_final": 52.0},
        {"scan_id": "S8", "mss_final": 51.0},
    ]
    _write_intraday_state(tmp_path, scans)
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        lambda code=None: tmp_path / "intraday_state.json",
    )
    monkeypatch.setattr("agent_reach.daily_run.intraday._today_str", lambda: "2026-08-27")

    settings = {
        "harness": {"reading_signals": {"enabled": True, "recovery_min_lookback": 52.0}},
        "intraday": {"trend_min_points": 2, "trend_delta_threshold": 1.0},
    }
    reading = resolve_harness_reading_signals(settings)
    assert reading.get("mixed_early_recovery") is True
    assert reading.get("mss_recovery") is True


def test_strength_filter_blocks_trim_on_strong_symbol(tmp_path, monkeypatch):
    scans = [
        {"scan_id": "S6", "mss_final": 50.0},
        {"scan_id": "S7", "mss_final": 51.0},
    ]
    _write_intraday_state(tmp_path, scans)
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        lambda code=None: tmp_path / "intraday_state.json",
    )
    monkeypatch.setattr("agent_reach.daily_run.intraday._today_str", lambda: "2026-08-27")

    reason = defensive_trim_blocked_by_strength(
        {"intraday": {"defensive_trim": {"max_symbol_change_pct": 1.0}}},
        trend="mixed",
        code="000725",
        snapshot={
            "change_pct": 3.85,
            "portfolio": {"holdings": [{"code": "000725", "change_pct": 3.85}]},
        },
    )
    assert reason is not None
    assert "3.85" in reason


def test_jingdongfang_case_blocked_at_0946(tmp_path, monkeypatch):
    scans = [
        {"scan_id": "S6", "mss_final": 48.0},
        {"scan_id": "S7", "mss_final": 51.0},
    ]
    _write_intraday_state(tmp_path, scans)
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        lambda code=None: tmp_path / "intraday_state.json",
    )
    monkeypatch.setattr("agent_reach.daily_run.intraday._today_str", lambda: "2026-08-27")

    settings = {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45, "min_cash_ratio": 0.5},
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001, "holding_lock_days": 1},
        "harness": {"reading_signals": {"enabled": True, "recovery_min_lookback": 52.0}},
        "intraday": {
            "trend_min_points": 2,
            "defensive_trim": {"max_symbol_change_pct": 1.0},
            "defensive_trim_min_mss": 40,
        },
        "harness_runtime": {
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
    }
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
        report={"code": "000725", "name": "京东方Ａ", "blocked": False},
        snapshot={
            "change_pct": 3.85,
            "portfolio": {
                "cash_ratio": 0.6,
                "holdings": [
                    {
                        "code": "000725",
                        "name": "京东方Ａ",
                        "shares": 900,
                        "cost": 5.74,
                        "price": 5.80,
                        "days_held": 2,
                        "change_pct": 3.85,
                    }
                ],
            },
            "symbols": [{"code": "000725", "price": 5.80, "change_pct": 3.85}],
        },
        settings=settings,
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
    )
    assert decision.action == "hold"
    assert decision.block_kind == "sell_defensive_trim"


def test_once_per_day_blocks_second_defensive_trim():
    allow, reason = evaluate_defensive_trim_sell(
        {
            "intraday": {"defensive_trim": {"once_per_symbol_per_day": True}},
            "harness_runtime": {"trend_policy": {"sell_trends": ["falling"]}},
        },
        lookback_mss=45.0,
        macro_veto=30.0,
        trend="falling",
        trade_signals={"defensive_trim": True},
        report={"code": "000725"},
        snapshot={"portfolio": {"holdings": []}},
        prior_trades=[
            {
                "action": "sell",
                "code": "000725",
                "portfolio_applied": True,
                "reasoning": "防御性减仓",
            }
        ],
    )
    assert allow is False
    assert reason is not None
    assert "不再重复" in reason


def test_defensive_trim_caps_short_hold_sell_ratio():
    settings = {
        "trading": {"holding_lock_days": 1},
        "intraday": {"defensive_trim": {"short_hold_sell_ratio": 0.25, "memory_sell_ratio": 0.35}},
        "harness_runtime": {
            "trade_signals": {"defensive_trim": True},
            "deep_loss_policy": {
                "loss_cny_threshold": 5000,
                "loss_pct_threshold": 10,
                "cover_ratio": 0.0,
                "sell_ratio": 0.5,
                "non_deep_loss_sell_ratio": 0.7,
            },
        },
    }
    holding = {
        "code": "000725",
        "name": "京东方Ａ",
        "shares": 900,
        "cost": 8.0,
        "days_held": 1,
    }
    enriched = {"000725": {"price": 5.8}}
    analysis = deep_loss_sell_analysis({}, holding, enriched, settings)
    assert analysis["sell_shares"] == 200
    assert analysis["sell_ratio"] == 0.25


def test_macro_warming_memory_suppresses_stale_mss_miss():
    state = HarnessState()
    state.entries["memory"]["miss"] = HarnessEntry(
        id="miss",
        kind="memory",
        title="MSS 预测偏离",
        content="MSS 预测偏离：下日调低进攻阈值或缩窄仓位",
        source="deterministic",
        job="close",
        evidence="close",
        created_at="2026-08-17T00:00:00+00:00",
        updated_at="2026-08-17T00:00:00+00:00",
    )
    state.entries["memory"]["warm"] = HarnessEntry(
        id="warm",
        kind="memory",
        title="宏观回暖",
        content="宏观回暖：读数驱动 Lookback MSS 51.0 / 最新 52.0 趋势 mixed",
        source="deterministic",
        job="intraday",
        evidence="intraday",
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )
    settings = {"harness": {"runtime_overlay_sources": ["memory"], "reading_signals": {"enabled": False}}}
    signals = resolve_harness_trade_signals(state, settings=settings)
    assert signals.get("defensive_trim") is False
    assert signals.get("mss_forecast_miss") is False
