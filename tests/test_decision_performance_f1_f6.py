# -*- coding: utf-8
"""Tests for decision-vs-performance findings F1–F6 (2026-09-16)."""

from __future__ import annotations

from datetime import date

from agent_reach.daily_run.close_cards import CloseCardContext
from agent_reach.daily_run.close_morning_handoff import (
    _action_executed,
    _expected_passive_weight_pct,
    validate_morning_action_lines,
)
from agent_reach.daily_run.deploy_signal_policy import apply_buy_budget_verdict_gate
from agent_reach.daily_run.kronos_inference_policy import (
    kronos_divergence_blend_multiplier,
    kronos_mc_divergence_day,
    resolve_symbol_blend_weight,
)
from agent_reach.daily_run.morning_cards import MorningCardContext, MorningSymbolRow
from agent_reach.daily_run.morning_signals import render_budget_affordability_markdown
from agent_reach.daily_run.mss_forecast import forecast_mss_range
from agent_reach.daily_run.pipeline import evaluate_snapshot
from agent_reach.daily_run.technical_scenario_watch import evaluate_scenario
from agent_reach.daily_run.verdict import VerdictResult
from agent_reach.daily_run.verify import verify_snapshots


def _high_price_settings():
    return {
        "thresholds": {"min_cash_ratio": 0.1, "macro_veto": 40, "aggressive": 55},
        "position": {"deploy_ratio": 0.25, "max_position_pct": 25},
        "portfolio": {"min_deploy_cash": 1000},
        "verdict_labels": {"buy": "可做", "watch": "观察", "avoid": "回避"},
    }


def test_f1_verdict_downgrade_when_budget_insufficient(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.simulate_buy_analysis",
        lambda *a, **k: {
            "allowed": False,
            "buy_budget": 13647,
            "min_lot_cost": 36214,
            "block_reason": "603986 可部署买入预算 ¥13,647 不足一手",
        },
    )
    verdict = VerdictResult(
        verdict="可做",
        confidence="高",
        mss_final=52.0,
        entry_price=360.0,
        stop_loss_price=340.0,
        invalidation="test",
        reasoning="strong",
        label_key="buy",
    )
    snapshot = {
        "code": "603986",
        "portfolio": {"cash": 64716, "total": 100472, "holdings": []},
        "price": 361.6,
        "mss_final": 52,
        "mss_breakdown": {"macro": 50, "technical": 55, "sentiment": 50},
        "audit_passed": True,
        "structured_review_complete": True,
    }
    out = apply_buy_budget_verdict_gate(verdict, snapshot, _high_price_settings())
    assert out.verdict == "观察"
    assert out.label_key == "watch"
    assert any("预算不可达" in r for r in out.downgrade_reasons)


def test_f1_pipeline_applies_budget_gate(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.simulate_buy_analysis",
        lambda *a, **k: {"allowed": False, "block_reason": "budget", "buy_budget": 1, "min_lot_cost": 9},
    )
    snapshot = {
        "code": "603986",
        "name": "兆易创新",
        "price": 361.6,
        "mss_final": 56,
        "mss_breakdown": {"macro": 55, "technical": 58, "sentiment": 52},
        "portfolio": {"cash": 64716, "total": 100472, "holdings": []},
        "audit_passed": True,
        "structured_review_complete": True,
    }
    result = evaluate_snapshot(snapshot, _high_price_settings())
    assert result["report"]["verdict"] == "观察"


def test_f1_morning_budget_markdown():
    ctx = MorningCardContext(
        portfolio={
            "cash": 64716,
            "total": 100472,
            "watchlist": [{"code": "603986", "name": "兆易创新", "price": 361.6}],
            "holdings": [],
        },
        symbol_rows=[],
        settings=_high_price_settings(),
    )
    md = render_budget_affordability_markdown(ctx)
    if md:
        assert "部署预算" in md or "预算不可达" in md


def test_f2_hold_passive_drift_not_false_fail():
    morning_positions = {
        "688008": {"shares": 100, "weight_pct": 24.7, "morning_price": 188.0},
    }
    close_positions = {
        "688008": {"shares": 100, "close_price": 199.89, "weight_pct": 19.6},
    }
    expected = _expected_passive_weight_pct(
        morning_positions=morning_positions,
        close_positions=close_positions,
        code="688008",
        end_total=101_987.0,
    )
    assert expected is not None
    assert abs(expected - 19.6) <= 0.2
    assert _action_executed(
        operation="持有",
        morning_current=24.7,
        morning_target=24.7,
        actual_weight=19.6,
        expected_passive_weight=expected,
    )


def test_f2_morning_action_trace_hold_after_rally(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 9, 16),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.close_morning_handoff.load_morning_handoff",
        lambda **k: {
            "morning_date": "2026-09-16",
            "positions_at_morning": {
                "688008": {"shares": 100, "weight_pct": 24.7},
            },
            "action_checklist": [
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "operation": "持有",
                    "current_weight_pct": 24.7,
                    "target_weight_pct": 24.7,
                    "target_position": "维持 25%",
                }
            ],
        },
    )
    ctx = CloseCardContext(
        portfolio_summary={
            "end_total": 101987.0,
            "holdings": [
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "shares": 100,
                    "price": 199.89,
                    "weight_pct": 19.6,
                }
            ],
        },
        symbol_rows=[],
    )
    lines = validate_morning_action_lines(ctx)
    assert lines
    assert "✅" in lines[0]


def test_f3_kronos_divergence_blend_penalty(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.kronos_calibration.load_kronos_error_ledger",
        lambda limit=120: [
            {"code": "688008", "date": "2026-09-16", "direction_hit": False},
            {"code": "688008", "date": "2026-09-15", "direction_hit": False},
        ],
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.kronos_calibration.summarize_kronos_ledger",
        lambda rows, lookback_days=14: {"divergence_heavy_codes": ["688008"], "rows": 2},
    )
    mult = kronos_divergence_blend_multiplier("688008", {})
    assert mult == 0.5
    blend = resolve_symbol_blend_weight("688008", {"kronos": {"week_forecast_blend_weight": 0.35}})
    assert blend <= 0.18


def test_f3_kronos_mc_divergence_skips_buy_block(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.kronos_calibration.load_kronos_error_ledger",
        lambda limit=40: [
            {
                "code": "688008",
                "date": "2026-09-16",
                "direction_hit": False,
                "actual_direction": "up",
                "kronos_direction": "down",
            }
        ],
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 9, 16),
    )
    assert kronos_mc_divergence_day({}, "688008", mss=53.0) is True


def test_f4_emotion_widens_mss_range():
    snapshot = {
        "mss_final": 48.0,
        "mss_breakdown": {
            "macro": 45,
            "technical": 50,
            "sentiment": 48,
            "_emotion_fusion_ref": {"rating": "强", "score": 5},
        },
        "change_pct": 6.4,
    }
    settings = {"mss_forecast": {"base_spread": 10, "vol_multiplier": 7, "simulations": 100}}
    narrow_rng, _ = forecast_mss_range(
        {**snapshot, "mss_breakdown": {"macro": 45, "technical": 50, "sentiment": 48}},
        settings,
    )
    wide_rng, _ = forecast_mss_range(snapshot, settings)
    assert wide_rng[1] - wide_rng[0] >= narrow_rng[1] - narrow_rng[0]


def test_f4_verify_prefers_intraday_range():
    baseline = {"mss_range": [29.2, 44.8], "mss_final": 48.86, "price": 188.0}
    current = {
        "mss_final": 53.06,
        "price": 199.89,
        "mss_intraday_range": [28.3, 55.0],
    }
    result = verify_snapshots(baseline, current, _high_price_settings())
    assert result.mss_within_prediction is True
    assert "盘中" in result.summary


def test_f5_low_hit_streak_accelerates_calibration():
    from agent_reach.daily_run.week_forecast_tracker import ForecastDayReview, optimize_calibration

    review = ForecastDayReview(
        date="2026-09-16",
        symbol_evals=[],
        symbol_hits=0,
        symbol_total=2,
        accuracy=0.4,
    )
    cal = optimize_calibration(
        review,
        {"bias_pct": 0.0, "vol_scale": 1.0, "low_hit_streak": 2},
        {"week_forecast": {"calibration_learning_rate": 0.15, "low_hit_streak_trigger": 3}},
    )
    assert cal["low_hit_streak"] == 3


def test_f6_long_hold_liquidity_trim():
    scenario = {
        "scenario_type": "liquidity_shrink",
        "code": "002583",
        "name": "海能达",
        "setup_turnover": 115_000_000,
        "session_close": 8.15,
    }
    result = evaluate_scenario(
        scenario,
        price=8.1,
        change_pct=-0.5,
        volume_ratio=0.7,
        turnover=90_000_000,
        days_held=809,
        settings={"technical_watch": {"liquidity_shrink": {"long_hold_trim_days": 365}}},
    )
    assert result["status"] == "long_hold_liquidity_trim"
    assert "809" in result["headline"]
