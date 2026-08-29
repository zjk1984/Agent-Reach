# -*- coding: utf-8
"""Tests for weekly signal cards (overview, holdings, strategy, outlook)."""

from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.weekly_report import WeeklyReport, render_weekly_sections
from agent_reach.daily_run.weekly_signals import (
    build_holdings_contribution_table,
    build_performance_overview_table,
    build_position_change_summary,
    build_strategy_validation,
    render_holdings_contribution_markdown,
    render_next_week_outlook_markdown,
    render_performance_overview_markdown,
    render_strategy_validation_markdown,
)


class TestPerformanceOverview:
    def test_overview_table_columns(self):
        table = build_performance_overview_table(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102300,
            weekly_metrics={
                "absolute_return_pct": 2.3,
                "excess_return_pct": 1.5,
                "benchmark": {"ok": True, "return_pct": 0.8},
            },
        )
        md = "\n".join(render_performance_overview_markdown(table))
        assert "| 指标 | 本周 | 近4周 | 年初至今 |" in md
        assert "组合收益率" in md
        assert "超额收益" in md
        assert "+2.3%" in md or "2.3%" in md


class TestHoldingsContribution:
    def test_sorted_with_tags(self):
        rows = build_holdings_contribution_table(
            [
                {"code": "300308", "name": "中际旭创", "market_value": 20000, "week_chg_pct": 8.5},
                {"code": "002273", "name": "水晶光电", "market_value": 15000, "week_chg_pct": 3.2},
                {"code": "000725", "name": "京东方", "market_value": 15000, "week_chg_pct": -2.1},
            ],
            start_total=100000,
        )
        assert rows[0]["name"] == "中际旭创"
        assert "最大贡献" in (rows[0].get("tags") or "")
        assert any("拖后腿" in (r.get("tags") or "") for r in rows)
        md = "\n".join(render_holdings_contribution_markdown(rows))
        assert "持仓周度复盘" in md
        assert "收益贡献" in md


class TestPositionChange:
    def test_position_change_summary(self):
        summary = build_position_change_summary(
            start_total=100000,
            end_total=100000,
            start_stock_mv=65000,
            end_stock_mv=72000,
            trade_log=[
                {
                    "date": "2026-08-06",
                    "side": "买",
                    "side_raw": "buy",
                    "name": "水晶光电",
                    "amount": 5000,
                },
                {
                    "date": "2026-08-08",
                    "side": "卖",
                    "side_raw": "sell",
                    "name": "京东方",
                    "amount": 2000,
                },
            ],
            daily_totals=[
                {"date": "2026-08-04", "total": 100000, "job": "close"},
                {"date": "2026-08-08", "total": 100000, "job": "close"},
            ],
        )
        assert summary["start_exposure_pct"] == 65.0
        assert summary["end_exposure_pct"] == 72.0
        assert "水晶光电" in summary["reason_text"]


class TestStrategyValidation:
    def test_strategy_win_rate_and_suggestion(self):
        data = build_strategy_validation(
            trade_log=[],
            trade_pnl_detail={
                "sells": [
                    {"date": "2026-08-05", "name": "A", "realized_pnl": 100},
                    {"date": "2026-08-06", "name": "B", "realized_pnl": -50},
                ]
            },
            prediction_verification={"featured_cases": []},
            prior_week_win_rate=40.0,
        )
        md = "\n".join(render_strategy_validation_markdown(data))
        assert "策略胜率" in md
        assert "盈亏比" in md
        assert "策略验证" in md


class TestWeeklySections:
    def test_render_weekly_sections_include_signal_cards(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102300,
            weekly_pnl=2300,
            weekly_pnl_pct=2.3,
            realized_pnl=0,
            performance_overview={
                "rows": [
                    {"metric": "组合收益率", "week": 2.3, "four_weeks": 5.1, "ytd": 12.4},
                    {"metric": "基准（沪深300）", "week": 0.8, "four_weeks": 1.2, "ytd": 3.5},
                    {"metric": "超额收益", "week": 1.5, "four_weeks": 3.9, "ytd": 8.9},
                ]
            },
            position_change={"start_exposure_pct": 65, "end_exposure_pct": 72, "reason_text": "测试"},
            holdings_contribution=[
                {
                    "rank": 1,
                    "name": "中际旭创",
                    "week_chg_pct": 8.5,
                    "weight_pct": 20,
                    "contribution_pct": 1.7,
                    "tags": "🌟 最大贡献",
                }
            ],
            strategy_validation={
                "signal_count": 3,
                "win_count": 2,
                "win_rate_pct": 66.7,
                "profit_loss_ratio": 1.5,
                "signals": [],
                "suggestions": ["维持现有参数"],
            },
            next_week_outlook={
                "operation_plan": [
                    {
                        "name": "中际旭创",
                        "action": "减仓",
                        "trigger": "反弹至 130 元",
                        "target_weight": "20% → 10%",
                        "stop_loss": "115.00 元",
                    }
                ],
                "risk_calendar": [
                    {
                        "date": "2026-08-13",
                        "event": "中际旭创财报",
                        "scope": "个股",
                        "severity": "🟡 中",
                    }
                ],
            },
        )
        labels = [s.label for s in render_weekly_sections(report)]
        assert "总览" in labels
        assert "持仓复盘" in labels
        assert "策略验证" in labels
        assert "下周展望" in labels

    @patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_week_manifests", return_value=[])
    def test_generate_weekly_report_populates_signals(
        self,
        mock_manifests,
        mock_ledger,
        mock_exa,
        snapshot,
        portfolio,
    ):
        from agent_reach.daily_run.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            snapshot,
            {"weekly_report": {"exa_sector_research": False}},
            as_of=date(2026, 8, 9),
            portfolio=portfolio,
        )
        assert report.performance_overview.get("rows")
        assert isinstance(report.holdings_contribution, list)
        assert report.strategy_validation is not None
        assert report.next_week_outlook is not None


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 40000,
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100, "cost": 250.0},
        ],
        "watchlist": [],
    }


@pytest.fixture
def snapshot(portfolio):
    return {
        "code": "688008",
        "name": "澜起科技",
        "price": 260.0,
        "portfolio": portfolio,
        "holdings": portfolio["holdings"],
    }
