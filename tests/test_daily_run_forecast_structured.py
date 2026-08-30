# -*- coding: utf-8
"""Tests for structured weekly forecast cards."""

from agent_reach.daily_run.forecast_operation_matrix import build_master_operation_rows
from agent_reach.daily_run.forecast_structured import (
    aggregate_symbol_week_prediction,
    attach_structured_forecast,
    build_market_prediction,
    build_tied_operation_plans,
    contains_vague_language,
    forecast_section_labels,
    render_prior_week_verify_markdown,
    render_structured_forecast_sections,
    verify_prior_week_predictions,
)
from agent_reach.daily_run.week_forecast import ForecastSection, render_forecast_sections


def test_forecast_section_labels_are_six():
    labels = forecast_section_labels()
    assert labels[0] == "上周验证"
    assert labels[1] == "操作总表"
    assert labels[-1] == "关键事件"
    assert len(labels) == 6


def test_aggregate_symbol_week_prediction_numeric_text():
    sym = {
        "code": "300308",
        "name": "中际旭创",
        "role": "holding",
        "base_price": 100.0,
        "days": {
            "2026-08-18": {"change_pct_range": [-1.0, 2.0], "expected_change_pct": 0.5},
            "2026-08-19": {"change_pct_range": [-0.5, 1.5], "expected_change_pct": 0.3},
        },
    }
    row = aggregate_symbol_week_prediction(sym)
    assert row is not None
    assert "中际旭创下周预测" in row["text"]
    assert not contains_vague_language(row["text"])


def test_build_market_prediction_format():
    pred = build_market_prediction(
        mss_daily={
            "2026-08-18": {"median": 52.0, "range": [50, 54]},
            "2026-08-22": {"median": 54.0, "range": [52, 56]},
        },
        calibration={"bias_pct": 0.0, "vol_scale": 1.0},
    )
    assert "沪深300" in pred["text"]
    assert "%" in pred["text"]
    assert not contains_vague_language(pred["text"])


def test_verify_prior_week_predictions_table():
    prior = {
        "week_start": "2026-08-18",
        "week_end": "2026-08-22",
        "trading_days": ["2026-08-18", "2026-08-19"],
        "structured_predictions": {
            "market": {
                "label": "下周大盘（沪深300）",
                "change_pct_low": 0.5,
                "change_pct_high": 1.5,
                "change_pct_mid": 1.0,
            },
            "symbols": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "base_price": 118.0,
                    "price_low": 110.0,
                    "price_high": 125.0,
                    "price_mid": 118.0,
                    "change_pct_low": -2.0,
                    "change_pct_high": 5.0,
                }
            ],
            "sectors": [],
        },
        "actuals": {
            "2026-08-18": {
                "symbols": {
                    "300308": {"change_pct": -1.0, "hit": True},
                }
            },
            "2026-08-19": {
                "symbols": {
                    "300308": {"change_pct": -0.8, "hit": True},
                }
            },
        },
    }
    verified = verify_prior_week_predictions(prior, settings={})
    assert verified["rows"]
    md = render_prior_week_verify_markdown(verified)
    assert "上周预测验证" in md
    assert "| 上周预测 | 实际结果 | 验证 | 偏差 |" in md


def test_build_tied_operation_plans_uses_master_rows():
    structured = {
        "symbols": [
            {
                "code": "300308",
                "name": "中际旭创",
                "price_low": 110.0,
                "price_mid": 118.0,
                "price_high": 125.0,
                "text": "中际旭创下周预测：区间 110-125 元，中枢 118 元",
            }
        ]
    }
    portfolio = {
        "total_value": 100000,
        "holdings": [{"code": "300308", "name": "中际旭创", "market_value": 20000}],
    }
    master_rows = build_master_operation_rows(portfolio=portfolio, structured=structured)
    plans = build_tied_operation_plans(structured, portfolio=portfolio, master_rows=master_rows)
    assert len(plans) == 1
    assert "→" in plans[0]["operation_plan"]
    assert "止损" in plans[0]["operation_plan"]


def test_render_structured_forecast_sections_order():
    forecast = {
        "week_start": "2026-08-24",
        "week_end": "2026-08-28",
        "calibration_used": {"hit_rate": 0.75},
        "structured_predictions": {
            "market": {"text": "下周大盘（沪深300）预测：+0.5% ~ +1.5%，中枢 +1.0%"},
            "sectors": [{"text": "AI板块下周预测：相对沪深300超额收益 +1% ~ +3%"}],
            "symbols": [],
        },
        "prior_week_verification": {
            "week_start": "2026-08-18",
            "week_end": "2026-08-22",
            "rows": [
                {
                    "prediction": "沪深300 +0.5%~+1.5%",
                    "actual": "+0.8%",
                    "verify": "✅ 命中区间",
                    "deviation": "0%",
                    "hit": True,
                }
            ],
            "hits": 1,
            "total": 1,
            "accuracy_pct": 100.0,
            "avg_deviation_pct": 0.0,
            "miss_reasons": [],
            "accuracy_trend": [{"accuracy_pct": 75.0}, {"accuracy_pct": 80.0}],
        },
        "operation_plans": [
            {
                "name": "中际旭创",
                "prediction_text": "110-125元，中枢118",
                "operation_plan": "回调至112元加仓至20%；突破125元持有；跌破108元止损至10%",
            }
        ],
        "operation_matrix": {
            "master_rows": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "current_weight_pct": 15,
                    "operation": "加仓",
                    "trigger": "回调至112元",
                    "target_weight": "15%→20%",
                    "stop_loss": "108元",
                },
                {
                    "code": "CASH",
                    "name": "现金",
                    "current_weight_pct": 85,
                    "operation": "—",
                    "trigger": "—",
                    "target_weight": "—",
                    "stop_loss": "—",
                },
            ],
            "position_guidance": {
                "summary": "下周建议整体仓位：50%-60%（当前15%）",
                "concentration": "单只股票不超过20%",
                "rationale": "测试",
            },
            "scenarios": [
                {"name": "基准", "probability_pct": 60, "trigger": "t1", "response": "r1"},
                {"name": "风险", "probability_pct": 25, "trigger": "t2", "response": "r2"},
                {"name": "乐观", "probability_pct": 15, "trigger": "t3", "response": "r3"},
            ],
            "timeline": [
                {
                    "date": "2026-08-28",
                    "event": "股指期货交割",
                    "scope": "大盘波动",
                    "severity_emoji": "🟡",
                    "response": "交割日避免开新仓",
                }
            ],
            "limitations": {"lines": ["不构成投资建议。"], "high_uncertainty_names": []},
        },
        "notes": [],
    }
    sections = render_structured_forecast_sections(forecast)
    labels = [label for label, _ in sections]
    assert labels == list(forecast_section_labels())
    assert "✅ 命中区间" in sections[0][1]
    assert "操作计划总表" in sections[1][1]
    assert "情景预案" in sections[2][1]
    assert "操作总表" in sections[4][1] or "详见「操作总表」" in sections[4][1]


def test_render_forecast_sections_first_is_prior_verify():
    sections = render_forecast_sections(
        {
            "week_start": "2026-08-24",
            "week_end": "2026-08-28",
            "mss_daily": {"2026-08-25": {"median": 52.0, "range": [50, 54]}},
            "symbols": {},
            "calibration_used": {"hit_rate": 0.6},
            "structured_predictions": {
                "market": {"text": "下周大盘（沪深300）预测：+0.2% ~ +1.2%，中枢 +0.7%"},
                "sectors": [],
                "symbols": [],
            },
            "prior_week_verification": {"rows": [], "accuracy_trend": []},
            "operation_plans": [],
            "risk_calendar": [],
            "notes": [],
        }
    )
    assert sections[0].label == "上周验证"
    assert sections[-1].label == "关键事件"
    assert all(isinstance(s, ForecastSection) for s in sections)


def test_attach_structured_forecast_populates_fields():
    forecast = {
        "week_start": "2026-08-24",
        "week_end": "2026-08-28",
        "trading_days": ["2026-08-25"],
        "symbols": {
            "688008": {
                "code": "688008",
                "name": "澜起科技",
                "role": "holding",
                "base_price": 80.0,
                "days": {
                    "2026-08-25": {
                        "change_pct_range": [-1.0, 2.0],
                        "expected_change_pct": 0.5,
                    }
                },
            }
        },
        "mss_daily": {"2026-08-25": {"median": 52.0, "range": [50, 54]}},
        "calibration_used": {"hit_rate": 0.5, "vol_scale": 1.0, "bias_pct": 0.0},
    }
    portfolio = {
        "total_value": 100000,
        "holdings": [{"code": "688008", "name": "澜起科技", "market_value": 30000}],
    }
    enriched = attach_structured_forecast(forecast, portfolio=portfolio, settings={})
    assert enriched.get("structured_predictions", {}).get("market")
    assert enriched.get("operation_plans")
    assert enriched.get("operation_matrix", {}).get("master_rows")


def test_build_master_operation_rows_uses_total_and_shares_price():
    portfolio = {
        "total": 104531,
        "cash": 61000,
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100, "price": 80.0},
            {"code": "300308", "name": "中际旭创", "shares": 50, "price": 120.0},
        ],
    }
    structured = {
        "symbols": [
            {"code": "688008", "name": "澜起科技", "confidence_pct": 70},
            {"code": "300308", "name": "中际旭创", "confidence_pct": 65},
        ]
    }
    rows = build_master_operation_rows(portfolio=portfolio, structured=structured)
    codes = {r["code"] for r in rows}
    assert "688008" in codes
    assert "300308" in codes
    cash_row = next(r for r in rows if r["code"] == "CASH")
    assert float(cash_row["current_weight_pct"]) < 100.0
    assert float(cash_row["current_weight_pct"]) > 50.0
