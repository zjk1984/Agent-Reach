# -*- coding: utf-8
"""Tests for Sunday forecast operation matrix (master table, scenarios, timeline)."""

from agent_reach.daily_run.forecast_operation_matrix import (
    build_forecast_operation_matrix,
    build_master_operation_rows,
    build_scenario_plans,
    render_limitations_markdown,
    render_master_operation_markdown,
    render_scenario_markdown,
    render_timeline_markdown,
)


def _sample_structured():
    return {
        "market": {
            "change_pct_low": 0.5,
            "change_pct_high": 1.5,
            "change_pct_mid": 1.0,
            "confidence_pct": 65,
        },
        "symbols": [
            {
                "code": "300308",
                "name": "中际旭创",
                "price_low": 108.0,
                "price_mid": 118.0,
                "price_high": 125.0,
                "confidence_pct": 75,
            },
            {
                "code": "002273",
                "name": "水晶光电",
                "price_low": 30.0,
                "price_mid": 35.0,
                "price_high": 38.0,
                "confidence_pct": 70,
            },
        ],
    }


def _sample_portfolio():
    return {
        "total_value": 100000,
        "holdings": [
            {"code": "300308", "name": "中际旭创", "market_value": 15000},
            {"code": "002273", "name": "水晶光电", "market_value": 10000},
        ],
    }


def test_master_operation_rows_include_cash_and_valid_ops():
    rows = build_master_operation_rows(
        portfolio=_sample_portfolio(),
        structured=_sample_structured(),
        outlook={
            "operation_plan": [
                {"code": "688008", "name": "澜起科技", "action": "新建仓", "trigger": "回调至80元"},
            ]
        },
    )
    ops = {r.get("operation") for r in rows if r.get("code") != "CASH"}
    assert ops.issubset({"加仓", "减仓", "持有", "新建仓", "清仓"})
    cash = next(r for r in rows if r.get("code") == "CASH")
    assert cash["name"] == "现金"
    assert float(cash["current_weight_pct"]) == 75.0


def test_master_operation_markdown_has_table_and_guidance():
    matrix = build_forecast_operation_matrix(
        portfolio=_sample_portfolio(),
        structured=_sample_structured(),
        outlook={"risk_calendar": [{"date": "2026-09-02", "event": "美国CPI", "scope": "大盘波动", "severity": "高"}]},
        forecast={"week_start": "2026-08-24"},
    )
    md = render_master_operation_markdown(matrix)
    assert "下周操作计划总表" in md
    assert "整体仓位" in md
    assert "| 股票 | 当前仓位 | 下周操作 | 触发条件 | 目标仓位 | 止损位 |" in md
    assert "中际旭创" in md
    assert "现金" in md


def test_master_operation_rows_watchlist_has_operation_fields():
    rows = build_master_operation_rows(
        portfolio={
            "total_value": 100000,
            "holdings": [{"code": "300308", "name": "中际旭创", "market_value": 15000}],
            "watchlist": [{"code": "603986", "name": "兆易创新"}],
        },
        structured={
            "symbols": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "price_low": 108.0,
                    "price_mid": 118.0,
                    "price_high": 125.0,
                    "confidence_pct": 75,
                },
                {
                    "code": "603986",
                    "name": "兆易创新",
                    "price_low": 180.0,
                    "price_mid": 200.0,
                    "price_high": 220.0,
                    "confidence_pct": 60,
                },
            ]
        },
        outlook={"operation_plan": []},
    )
    watch = next(r for r in rows if r.get("code") == "603986")
    assert watch["operation"] != "—"
    assert watch["trigger"] != "—"
    assert watch["target_weight"] != "—"
    assert watch["stop_loss"] != "—"


def test_scenario_plans_three_rows():
    rows = build_master_operation_rows(
        portfolio=_sample_portfolio(),
        structured=_sample_structured(),
    )
    scenarios = build_scenario_plans(structured=_sample_structured(), master_rows=rows)
    assert len(scenarios) == 3
    assert sum(int(s["probability_pct"]) for s in scenarios) == 100
    md = render_scenario_markdown({"scenarios": scenarios})
    assert "情景预案" in md
    assert "基准" in md
    assert "风险" in md


def test_timeline_and_limitations_render():
    matrix = build_forecast_operation_matrix(
        portfolio=_sample_portfolio(),
        structured=_sample_structured(),
        outlook={
            "risk_calendar": [
                {"date": "2026-09-02", "event": "美国CPI数据公布", "scope": "大盘波动", "severity": "高"},
            ]
        },
        forecast={"week_start": "2026-08-24"},
    )
    timeline_md = render_timeline_markdown(matrix)
    assert "关键时间节点" in timeline_md
    assert "🔴" in timeline_md
    assert "应对建议" in timeline_md

    limit_md = render_limitations_markdown(matrix)
    assert "预测局限性" in limit_md
    assert "不构成投资建议" in limit_md
