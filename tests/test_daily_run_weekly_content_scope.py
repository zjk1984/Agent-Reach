# -*- coding: utf-8
"""Tests for weekly report content deduplication."""

from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.weekly_content_scope import (
    build_weekly_macro_brief,
    enrich_trade_log_with_pnl,
    render_holdings_stock_logic_markdown,
    render_market_environment_markdown,
    render_week_key_events_markdown,
    render_weekly_prediction_verify_markdown,
    render_weekly_trade_log_compact_markdown,
    summarize_week_key_events,
    summarize_week_prediction_verification,
)
from agent_reach.daily_run.weekly_report import (
    WeeklyReport,
    _render_holdings_lines,
    _render_market_lines,
    _render_pnl_lines,
    render_weekly_sections,
)


class TestWeeklyTradeLogCompact:
    def test_compact_trade_log_columns(self):
        rows = enrich_trade_log_with_pnl(
            [
                {
                    "date": "2026-08-05",
                    "name": "澜起科技",
                    "code": "688008",
                    "side": "卖",
                    "side_raw": "sell",
                    "price": 85.0,
                    "shares": 100,
                }
            ],
            {
                "sells": [
                    {
                        "date": "2026-08-05",
                        "code": "688008",
                        "shares": 100,
                        "realized_pnl": 1500.0,
                    }
                ]
            },
        )
        md = "\n".join(
            render_weekly_trade_log_compact_markdown(rows, {"ok": True, "buy_total": 0, "sell_total": 8500})
        )
        assert "| 日期 | 操作 | 盈亏 |" in md
        assert "¥+1,500" in md
        assert "价格" not in md


class TestWeeklyKeyEvents:
    def test_one_liner_with_close_ref(self):
        events = summarize_week_key_events(
            [
                {
                    "job": "close",
                    "_run_date": "2026-08-06",
                    "payload": {
                        "symbol_results": [
                            {
                                "result": {
                                    "verify": {
                                        "name": "中际旭创",
                                        "price_delta_pct": -10.0,
                                    }
                                }
                            }
                        ]
                    },
                }
            ],
            trades=[],
        )
        md = "\n".join(render_week_key_events_markdown(events))
        assert "中际旭创" in md
        assert "详见" in md and "收盘卡片" in md


class TestWeeklyMacroBrief:
    def test_only_measurable_impact(self):
        items = build_weekly_macro_brief(
            portfolio={
                "holdings": [{"code": "688008", "name": "澜起科技", "sector": "半导体"}],
            },
            macro_signals={
                "hot_topics": [
                    {"title": "半导体政策利好出台"},
                    {"title": "某明星八卦"},
                ]
            },
            sector_snapshot={
                "sectors": [{"sector": "半导体", "avg_change_pct": 2.5}],
            },
            holdings=[{"sector": "半导体", "week_chg_pct": 2.5}],
            limit=5,
        )
        assert 1 <= len(items) <= 5
        assert all("影响：" in str(i.get("impact") or "") for i in items)
        assert not any("八卦" in str(i.get("title") or "") for i in items)


class TestWeeklyPredictionVerify:
    def test_summary_table_and_improvements(self):
        data = summarize_week_prediction_verification(
            [
                {
                    "job": "close",
                    "_run_date": "2026-08-05",
                    "payload": {
                        "result": {
                            "forecast_review": {
                                "symbol_evals": [
                                    {
                                        "code": "688008",
                                        "name": "澜起科技",
                                        "predicted_direction": "up",
                                        "actual_change_pct": 1.5,
                                        "hit": True,
                                    },
                                    {
                                        "code": "002273",
                                        "name": "水晶光电",
                                        "predicted_direction": "down",
                                        "actual_change_pct": 2.0,
                                        "hit": False,
                                    },
                                ],
                                "mss_hit": True,
                                "mss_predicted": [45, 55],
                                "mss_actual": 50,
                            }
                        }
                    },
                }
            ],
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
        )
        md = "\n".join(render_weekly_prediction_verify_markdown(data))
        assert "预测类型" in md
        assert "命中次数" in md
        assert "典型案例" in md or "标的涨跌" in md


class TestWeeklySectionDedup:
    def test_sections_drop_xueqiu_hot_card(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            weekly_metrics={"benchmark": {"ok": True, "return_pct": 1.0}},
            macro_signals={"hot_stocks": [{"name": "测试"}]},
            prediction_verification={
                "summary_rows": [
                    {"type": "标的涨跌", "total": 2, "hits": 1, "accuracy_pct": 50.0}
                ],
                "featured_cases": [],
                "improvements": ["需改进反转信号识别"],
            },
        )
        labels = [s.label for s in render_weekly_sections(report)]
        assert "雪球热门" not in labels
        assert "总览" in labels
        assert "市场环境" in labels
        assert "预测验证" in labels

    def test_pnl_lines_no_duplicate_trade_detail(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=500,
            trade_log_display=[
                {"date": "2026-08-05", "operation": "卖出澜起科技 100股@85.00", "pnl": 500.0}
            ],
            trade_reconciliation={"ok": True, "buy_total": 0, "sell_total": 8500},
            trade_pnl_detail={"sells": [{"name": "澜起科技", "realized_pnl": 500}]},
        )
        text = "\n".join(_render_pnl_lines(report))
        assert "总览" in text
        assert "本周交易日志" not in text
        assert "股票盈亏明细" not in text
        assert "成交现金流" not in text

    @patch("agent_reach.daily_run.eastmoney_market.fetch_indices", return_value={"sh000300": {}})
    def test_market_card_once(self, _mock_fetch):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            macro_brief=[
                {
                    "title": "半导体政策",
                    "impact": "影响：导致 半导体 上涨 2.50%",
                }
            ],
            market_review_weekly={"days_with_data": 5, "dominant_mainline": "科技"},
            sector_snapshot={
                "fetch_ok": True,
                "as_of_label": "截至 2026-08-08 15:00",
                "sectors": [{"sector": "半导体", "avg_change_pct": 2.5, "symbols": []}],
            },
        )
        text = "\n".join(_render_market_lines(report))
        assert text.count("市场环境") >= 1
        assert "RedFox vs 60s" not in text
        assert "板块深度" not in text

    def test_holdings_stock_logic_only(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            weekly_metrics={"benchmark": {"ok": True, "return_pct": 1.0}},
            holdings=[
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "week_chg": 1000,
                    "week_chg_pct": 3.0,
                    "unrealized_pnl": -100,
                }
            ],
            holdings_as_of="截至 2026-08-08 周五收盘",
        )
        text = "\n".join(_render_holdings_lines(report))
        assert "个股逻辑" in text
        assert "相对基准" in text
        assert "今日" not in text
