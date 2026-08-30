# -*- coding: utf-8
"""Tests for Sunday forecast advanced insights."""

from datetime import date

from agent_reach.daily_run.forecast_advanced import (
    build_forecast_advanced_insights,
    build_market_prediction_scatter,
    build_model_consistency,
    build_prior_operation_execution,
    build_stress_tests,
    render_model_consistency_markdown,
    render_prior_operation_execution_markdown,
    render_scatter_history_markdown,
    render_stress_tests_markdown,
)


def _prior_forecast():
    return {
        "week_start": "2026-08-18",
        "week_end": "2026-08-22",
        "trading_days": ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22"],
        "structured_predictions": {
            "symbols": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "base_price": 115.0,
                    "price_low": 108.0,
                    "price_high": 125.0,
                    "change_pct_mid": 2.0,
                }
            ]
        },
        "operation_matrix": {
            "master_rows": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "加仓",
                    "trigger": "回调至112元",
                    "target_weight": "15%→20%",
                    "current_weight_pct": 15,
                }
            ]
        },
        "actuals": {
            "2026-08-18": {"symbols": {"300308": {"change_pct": -1.0}}},
            "2026-08-19": {"symbols": {"300308": {"change_pct": -0.5}}},
            "2026-08-20": {"symbols": {"300308": {"change_pct": 0.2}}},
            "2026-08-21": {"symbols": {"300308": {"change_pct": 0.3}}},
            "2026-08-22": {"symbols": {"300308": {"change_pct": 0.5}}},
        },
    }


def test_render_scatter_history_markdown():
    scatter = {
        "index_name": "沪深300",
        "points": [
            {"predicted_mid_pct": 1.0, "actual_pct": 0.8, "deviation_pct": -0.2},
            {"predicted_mid_pct": 0.5, "actual_pct": -1.2, "deviation_pct": -1.7},
        ],
        "avg_abs_deviation_pct": 0.95,
        "direction_hits": 1,
        "direction_total": 2,
        "direction_accuracy_pct": 50.0,
        "bias_pct": -0.95,
    }
    md = render_scatter_history_markdown(scatter)
    assert "第1周" in md
    assert "预测+1.0%" in md
    assert "方向准确率" in md


def test_build_model_consistency_summary():
    forecast = {
        "symbols": {
            "300308": {
                "name": "中际旭创",
                "role": "holding",
                "base_price": 118.0,
                "days": {
                    "2026-08-25": {"expected_change_pct": 0.8, "change_pct_range": [0, 1.5]},
                },
            }
        },
        "kronos_paths": {
            "300308": {"available": True, "cum_change_pct": 1.2},
        },
        "structured_predictions": {
            "symbols": [
                {"code": "300308", "name": "中际旭创", "confidence_pct": 70},
            ]
        },
    }
    enriched = {"300308": {"mss_final": 58, "price": 118, "ma20": 110}}
    rows = build_model_consistency(
        forecast=forecast,
        enriched_map=enriched,
    )
    assert rows
    md = render_model_consistency_markdown(rows)
    assert "模型一致性" in md
    assert "中际旭创" in md


def test_stress_tests_render():
    tests = build_stress_tests(
        portfolio={
            "total_value": 100000,
            "holdings": [{"code": "300308", "name": "中际旭创", "market_value": 60000}],
        },
        matrix={"position_guidance": {"current_cash_pct": 40}},
    )
    md = render_stress_tests_markdown(tests)
    assert "压力测试" in md
    assert "暴跌5%" in md or "大盘暴跌" in md


def test_prior_operation_execution():
    block = build_prior_operation_execution(_prior_forecast(), settings={})
    assert block.get("lines")
    md = render_prior_operation_execution_markdown(block)
    assert "上周操作建议回顾" in md
    assert "112元" in md


def test_build_forecast_advanced_insights_bundle():
    forecast = {
        "week_start": "2026-08-24",
        "week_end": "2026-08-28",
        "symbols": {
            "300308": {
                "name": "中际旭创",
                "days": {"2026-08-25": {"expected_change_pct": 0.5}},
            }
        },
        "structured_predictions": {
            "market": {"change_pct_mid": 0.8, "index_name": "沪深300"},
            "symbols": [{"code": "300308", "name": "中际旭创", "confidence_pct": 68}],
        },
    }
    insights = build_forecast_advanced_insights(
        forecast=forecast,
        prior_forecast=_prior_forecast(),
        portfolio={"total_value": 100000, "holdings": [{"code": "300308", "market_value": 50000}]},
        matrix={"position_guidance": {"current_cash_pct": 50}},
        enriched_map={"300308": {"mss_final": 52, "price": 118, "ma20": 115}},
        settings={},
    )
    assert "scatter" in insights
    assert "model_consistency" in insights
    assert "stress_tests" in insights
    assert "prior_operation_execution" in insights
