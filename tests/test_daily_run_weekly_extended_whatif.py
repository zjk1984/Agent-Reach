# -*- coding: utf-8
"""Tests for weekly extended what-if builders."""

from datetime import date

from agent_reach.daily_run.weekly_extended_whatif import (
    build_weekly_forecast_calibrate_whatif,
    build_weekly_kronos_whatif,
    build_weekly_optimizer_whatif,
)


def test_forecast_calibrate_whatif_counts_divergence(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_forecast.load_forecast",
        lambda ws: {
            "symbols": {
                "688008": {"kronos_divergence_days": ["2026-08-11", "2026-08-12"]},
                "300308": {"kronos_divergence_days": ["2026-08-13"]},
            },
            "calibration_used": {"base_spread": 9.0},
        },
    )
    result = build_weekly_forecast_calibrate_whatif(
        week_start=date(2026, 8, 11),
        week_end=date(2026, 8, 15),
    )
    assert result.skipped is False
    assert result.divergence_symbol_days == 3
    assert result.divergence_symbols == 2


def test_optimizer_whatif_detects_runtime_lag():
    mss_summary = [
        {"date": "2026-08-11", "job": "close", "mss_final": 35.0},
        {"date": "2026-08-12", "job": "close", "mss_final": 58.0},
        {"date": "2026-08-13", "job": "close", "mss_final": 36.0},
        {"date": "2026-08-14", "job": "close", "mss_final": 57.0},
    ]
    daily_totals = [
        {"date": "2026-08-11", "job": "close", "total": 100000},
        {"date": "2026-08-12", "job": "close", "total": 101000},
        {"date": "2026-08-13", "job": "close", "total": 99500},
        {"date": "2026-08-14", "job": "close", "total": 100200},
    ]
    settings = {
        "optimizer": {"harness_evolve": True, "default_objective": "total_return"},
        "backtest": {"default_initial_capital": 100000, "commission_rate": 0.0015},
        "rejected_strategies": {"weekly_whatif": {"optimizer_score_delta_min": 0.0}},
    }
    result = build_weekly_optimizer_whatif(
        week_start=date(2026, 8, 11),
        week_end=date(2026, 8, 15),
        mss_summary=mss_summary,
        daily_totals=daily_totals,
        settings=settings,
    )
    assert result.skipped is False
    assert result.trials > 0
    assert result.best_params.get("macro_veto") is not None


def test_kronos_whatif_from_buy_block_reason():
    result = build_weekly_kronos_whatif(
        week_start=date(2026, 8, 11),
        week_end=date(2026, 8, 15),
        manifests=[],
        buy_rules_whatif={
            "skipped": False,
            "rows": [
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "block_reason": "Kronos 偏弱 2.1%，暂缓买入",
                },
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "block_reason": "Kronos 偏弱 1.5%，暂缓买入",
                },
            ],
        },
    )
    assert result.skipped is False
    assert result.kronos_blocked_signals == 2
