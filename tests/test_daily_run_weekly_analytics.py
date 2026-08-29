# -*- coding: utf-8
"""Tests for weekly-only analytics (trends, attribution, health, issues)."""

from datetime import date
from pathlib import Path

from agent_reach.daily_run.weekly_analytics import (
    build_brinson_attribution,
    build_four_week_trends,
    build_pending_issues,
    build_strategy_parameter_health,
    load_prior_weekly_issues,
    render_brinson_attribution_markdown,
    render_four_week_trends_markdown,
    render_pending_issues_markdown,
    render_strategy_health_markdown,
    save_weekly_issues,
)
from agent_reach.daily_run.weekly_report import WeeklyReport, render_weekly_sections


class TestFourWeekTrends:
    def test_build_four_week_trends_structure(self):
        data = build_four_week_trends(
            week_end=date(2026, 8, 8),
            current_return_pct=2.5,
            current_risk={"max_drawdown_pct": 1.2, "win_rate_pct": 60.0},
            current_strategy_win_rate=55.0,
        )
        assert len(data["weeks"]) == 4
        assert data["weeks"][-1]["label"] == "本周"
        assert data["weeks"][-1]["return_pct"] == 2.5
        md = "\n".join(render_four_week_trends_markdown(data))
        assert "近4周趋势" in md
        assert "W-1" in md or "W-2" in md


class TestBrinsonAttribution:
    def test_sector_alpha_beta(self):
        data = build_brinson_attribution(
            holdings=[
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "sector": "半导体",
                    "market_value": 26000,
                    "week_chg_pct": 3.0,
                },
                {
                    "code": "002273",
                    "name": "水晶光电",
                    "sector": "光学",
                    "market_value": 10000,
                    "week_chg_pct": -1.0,
                },
            ],
            start_total=100000,
            weekly_pnl_pct=1.5,
            sector_snapshot={
                "sectors": [
                    {"sector": "半导体", "weight_pct": 26, "avg_change_pct": 2.0},
                    {"sector": "光学", "weight_pct": 10, "avg_change_pct": -0.5},
                ]
            },
            prediction_verification={
                "summary_rows": [
                    {"type": "趋势预测", "total": 4, "hits": 3, "accuracy_pct": 75.0},
                    {"type": "反转预测", "total": 2, "hits": 0, "accuracy_pct": 0.0},
                ]
            },
            trade_pnl_detail={"sells": [{"realized_pnl": 100}, {"realized_pnl": -50}]},
            pnl_attribution={"held_week_chg": 800, "realized_pnl": 50},
        )
        assert data.get("sector_beta_pct") is not None
        assert data.get("stock_alpha_pct") is not None
        assert data.get("interpretation")
        md = "\n".join(render_brinson_attribution_markdown(data))
        assert "归因分析" in md
        assert "beta" in md.lower() or "板块" in md


class TestStrategyHealth:
    def test_concentration_warnings(self):
        data = build_strategy_parameter_health(
            holdings=[
                {"code": "688008", "name": "澜起科技", "market_value": 30000},
            ],
            sector_snapshot={"sectors": [{"sector": "半导体", "weight_pct": 45}]},
            trade_log=[{"amount": 60000}],
            start_total=100000,
            end_total=100000,
            strategy_validation={"win_rate_pct": 40, "signal_count": 5},
        )
        assert data["status"] in ("warn", "alert")
        assert len(data["warnings"]) >= 1
        md = "\n".join(render_strategy_health_markdown(data))
        assert "策略参数健康度" in md

    def test_healthy_portfolio(self):
        data = build_strategy_parameter_health(
            holdings=[
                {"code": "688008", "name": "A", "market_value": 15000},
                {"code": "002273", "name": "B", "market_value": 15000},
            ],
            sector_snapshot={
                "sectors": [
                    {"sector": "半导体", "weight_pct": 15},
                    {"sector": "光学", "weight_pct": 15},
                ]
            },
            trade_log=[{"amount": 5000}],
            start_total=100000,
            end_total=100000,
            strategy_validation={"win_rate_pct": 60, "signal_count": 3},
        )
        assert data["status"] == "ok"


class TestPendingIssues:
    def test_week_over_week_tracking(self, tmp_path, monkeypatch):
        issues_path = tmp_path / "weekly_issues.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.weekly_analytics._ISSUES_PATH", issues_path)

        prior = {
            "week_end": "2026-08-01",
            "issues": [
                {
                    "id": "abc123",
                    "title": "中际旭创止损信号连续 2 周延迟",
                    "detail": "需优化",
                    "priority": "high",
                    "category": "skill",
                    "status": "open",
                },
                {
                    "id": "done99",
                    "title": "已修复的问题",
                    "detail": "",
                    "priority": "low",
                    "category": "workflow",
                    "status": "open",
                },
            ],
        }
        save_weekly_issues(
            {
                "week_end": "2026-08-01",
                "open": prior["issues"],
                "resolved_this_week": [],
                "counts": {"open": 2},
            }
        )

        loaded = load_prior_weekly_issues(date(2026, 8, 4))
        assert loaded is not None

        snapshot = build_pending_issues(
            week_end=date(2026, 8, 8),
            process_improvements=[
                {
                    "title": "中际旭创止损信号连续 2 周延迟，需优化",
                    "detail": "still open",
                    "priority": "high",
                    "category": "skill",
                },
                {"title": "本周新增问题", "detail": "x", "priority": "medium", "category": "workflow"},
            ],
            strategy_health={"warnings": []},
            strategy_validation={"suggestions": []},
            prior_snapshot=loaded,
        )
        assert snapshot["counts"]["carried"] >= 1
        assert snapshot["counts"]["resolved"] >= 1
        assert snapshot["counts"]["new"] >= 1

        md = "\n".join(render_pending_issues_markdown(snapshot))
        assert "待解决问题" in md
        assert "持续跟踪" in md or "本周新增" in md


class TestWeeklySections:
    def test_new_sections_in_render(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            four_week_trends={
                "weeks": [{"label": "本周", "return_pct": 2.0, "win_rate_pct": 60, "max_drawdown_pct": 1.0}],
                "summary": {"assessment": "策略持续有效（近4周多数盈利）"},
            },
            brinson_attribution={
                "sector_beta_pct": 1.2,
                "stock_alpha_pct": 0.8,
                "interpretation": "选股 alpha 主导",
                "sector_rows": [],
            },
            strategy_health={
                "status": "ok",
                "checks": [{"ok": True, "message": "单股集中度 20.0% 正常", "severity": "ok"}],
            },
            pending_issues={
                "open": [{"title": "测试问题", "priority": "high"}],
                "new_this_week": [{"title": "测试问题"}],
                "counts": {"open": 1, "new": 1},
            },
        )
        labels = [s.label for s in render_weekly_sections(report)]
        assert "归因分析" in labels
        assert "待办事项" in labels
