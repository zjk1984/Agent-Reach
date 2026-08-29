# -*- coding: utf-8
"""Tests for weekly card metrics (return, risk, trades, sectors)."""

from datetime import date
from unittest.mock import patch

import pytest

from agent_reach.daily_run.weekly_card_metrics import (
    build_holdings_sector_snapshot,
    build_weekly_return_metrics,
    build_weekly_risk_metrics,
    fetch_benchmark_weekly_return,
    flatten_ledger_trades,
    reconcile_week_trades,
    render_holdings_sector_markdown,
    render_weekly_return_markdown,
    render_weekly_risk_markdown,
    render_weekly_trade_log_markdown,
)
from agent_reach.daily_run.weekly_report import (
    WeeklyReport,
    _render_holdings_lines,
    _render_market_lines,
    _render_pnl_lines,
    generate_weekly_report,
    render_weekly_markdown,
)


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 40000,
        "cash_ratio": 0.4,
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100, "cost": 250.0},
            {"code": "002273", "name": "水晶光电", "shares": 300, "cost": 30.0},
        ],
        "watchlist": [
            {"code": "603986", "name": "兆易创新"},
        ],
    }


@pytest.fixture
def snapshot(portfolio):
    return {
        "code": "688008",
        "name": "澜起科技",
        "price": 260.0,
        "change_pct": 2.5,
        "portfolio": portfolio,
        "watchlist": portfolio["watchlist"],
        "holdings": portfolio["holdings"],
    }


class TestWeeklyReturnMetrics:
    def test_build_weekly_return_metrics_with_benchmark(self):
        with patch(
            "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
            return_value={
                "name": "沪深300",
                "return_pct": 1.5,
                "ok": True,
                "start_price": 4000,
                "end_price": 4060,
            },
        ):
            metrics = build_weekly_return_metrics(
                week_start=date(2026, 8, 4),
                week_end=date(2026, 8, 8),
                start_total=100000,
                end_total=102000,
                weekly_pnl=2000,
                weekly_pnl_pct=2.0,
            )
        assert metrics["absolute_return_pct"] == 2.0
        assert metrics["costs_included"] is True
        assert metrics["excess_return_pct"] == 0.5

    def test_render_weekly_return_markdown(self):
        md = "\n".join(
            render_weekly_return_markdown(
                {
                    "start_total": 100000,
                    "end_total": 102000,
                    "absolute_return_pct": 2.0,
                    "absolute_return_amount": 2000,
                    "costs_note": "基于实际账户净值，已含 ledger 记录的买卖佣金",
                    "benchmark": {"ok": True, "name": "沪深300", "return_pct": 1.5, "start_price": 4000, "end_price": 4060},
                    "excess_return_pct": 0.5,
                }
            )
        )
        assert "本周收益（实际净值）" in md
        assert "周度收益率" in md
        assert "超额收益" in md
        assert "佣金" in md


class TestWeeklyTradeLog:
    def test_flatten_ledger_trades(self):
        rows = flatten_ledger_trades(
            [
                {
                    "at": "2026-08-05T02:00:00+00:00",
                    "actions": [
                        {
                            "side": "buy",
                            "code": "688008",
                            "name": "澜起科技",
                            "price": 80.0,
                            "shares": 100,
                            "amount": 8000.0,
                            "commission": 12.0,
                        }
                    ],
                }
            ]
        )
        assert len(rows) == 1
        assert rows[0]["side"] == "买"
        assert rows[0]["commission"] == 12.0

    def test_reconcile_week_trades_ok(self):
        trades = [
            {
                "at": "2026-08-05",
                "actions": [
                    {
                        "side": "buy",
                        "amount": 10000.0,
                        "commission": 15.0,
                    }
                ],
            }
        ]
        rec = reconcile_week_trades(
            trades=trades,
            start_cash=50000.0,
            end_cash=39985.0,
            start_stock_mv=50000.0,
            end_stock_mv=60000.0,
        )
        assert rec["buy_total"] == 10015.0
        assert rec["cash_delta"] == -10015.0
        assert rec["stock_mv_delta"] == 10000.0
        assert rec["ok"] is True

    def test_render_trade_log_markdown(self):
        md = "\n".join(
            render_weekly_trade_log_markdown(
                [
                    {
                        "date": "2026-08-05",
                        "name": "澜起科技",
                        "side": "买",
                        "price": 80.0,
                        "shares": 100,
                        "amount": 8000.0,
                        "commission": 12.0,
                    }
                ],
                {"ok": True, "buy_total": 8012.0, "sell_total": 0, "cash_delta": -8012, "stock_mv_delta": 8000},
            )
        )
        assert "本周交易日志" in md
        assert "ledger 实际成交" in md
        assert "流水校验" in md


class TestWeeklyRiskMetrics:
    def test_build_weekly_risk_metrics(self):
        risk = build_weekly_risk_metrics(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            daily_totals=[
                {"date": "2026-08-04", "total": 100000, "job": "close"},
                {"date": "2026-08-05", "total": 101000, "job": "close"},
                {"date": "2026-08-06", "total": 99500, "job": "close"},
                {"date": "2026-08-07", "total": 100500, "job": "close"},
                {"date": "2026-08-08", "total": 102000, "job": "close"},
            ],
        )
        assert risk["window_label"].startswith("本周")
        assert risk["max_drawdown_pct"] is not None
        assert risk["volatility_ann_pct"] is not None
        assert risk["win_rate_pct"] is not None

    def test_render_weekly_risk_markdown(self):
        md = "\n".join(
            render_weekly_risk_markdown(
                {
                    "window_label": "本周 5 个交易日",
                    "max_drawdown_pct": 1.5,
                    "volatility_ann_pct": 12.0,
                    "win_rate_pct": 60.0,
                    "benchmark": {
                        "ok": True,
                        "name": "沪深300",
                        "max_drawdown_pct": 0.8,
                        "volatility_ann_pct": 10.0,
                        "win_rate_pct": 55.0,
                    },
                }
            )
        )
        assert "本周风险指标" in md
        assert "最大回撤" in md
        assert "波动率" in md
        assert "胜率" in md


class TestHoldingsSectorSnapshot:
    @patch("agent_reach.daily_run.eastmoney_market.fetch_indices", return_value={})
    def test_fetch_failure_marks_warning(self, _mock_fetch):
        snap = build_holdings_sector_snapshot(
            [{"code": "688008", "name": "澜起科技", "sector": "半导体", "change_pct": 1.2}]
        )
        assert snap["fetch_ok"] is False
        md = "\n".join(render_holdings_sector_markdown(snap))
        assert "⚠️ 数据获取失败" in md
        assert "持仓相关板块" in md

    @patch(
        "agent_reach.daily_run.eastmoney_market.fetch_indices",
        return_value={"sh000300": {"price": 4000}},
    )
    def test_only_holdings_sectors(self, _mock_fetch):
        snap = build_holdings_sector_snapshot(
            [
                {"code": "688008", "name": "澜起科技", "sector": "半导体", "change_pct": 1.2},
                {"code": "002273", "name": "水晶光电", "sector": "光学", "change_pct": -0.5},
            ]
        )
        assert len(snap["sectors"]) == 2
        sectors = {r["sector"] for r in snap["sectors"]}
        assert sectors == {"半导体", "光学"}


class TestWeeklyReportIntegration:
    @patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_week_manifests", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[])
    @patch(
        "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
        return_value={"ok": True, "name": "沪深300", "return_pct": 0.5},
    )
    @patch("agent_reach.daily_run.eastmoney_market.fetch_indices", return_value={"sh000300": {}})
    def test_generate_weekly_report_populates_card_metrics(
        self,
        _mock_indices,
        _mock_bench,
        mock_ledger,
        mock_manifests,
        mock_exa,
        snapshot,
        portfolio,
    ):
        report = generate_weekly_report(
            snapshot,
            {"weekly_report": {"exa_sector_research": False}},
            as_of=date(2026, 8, 9),
            portfolio=portfolio,
        )
        assert report.weekly_metrics
        assert report.risk_metrics
        assert "周五收盘" in report.holdings_as_of
        assert "688008" in {h["code"] for h in report.holdings}

        md = render_weekly_markdown(report)
        assert "收益总览" in md or "总览" in md
        assert "持仓复盘" in md or "持仓周度复盘" in md

    def test_render_pnl_lines_uses_new_sections(self):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            weekly_metrics={
                "start_total": 100000,
                "end_total": 102000,
                "absolute_return_pct": 2.0,
                "absolute_return_amount": 2000,
                "costs_note": "基于实际账户净值，已含 ledger 记录的买卖佣金",
                "benchmark": {"ok": True, "name": "沪深300", "return_pct": 1.0, "start_price": 4000, "end_price": 4040},
                "excess_return_pct": 1.0,
            },
            risk_metrics={
                "window_label": "本周 5 个交易日",
                "max_drawdown_pct": 1.0,
                "volatility_ann_pct": 10.0,
                "win_rate_pct": 50.0,
                "benchmark": {"ok": True, "name": "沪深300", "max_drawdown_pct": 0.5, "volatility_ann_pct": 8.0, "win_rate_pct": 45.0},
            },
            trade_log=[],
            trade_reconciliation={"ok": True, "buy_total": 0, "sell_total": 0, "cash_delta": 0, "stock_mv_delta": 0},
        )
        text = "\n".join(_render_pnl_lines(report))
        assert "收益总览" in text or "本周" in text
        assert "本周风险指标" in text
        assert "股票盈亏明细" not in text

    @patch("agent_reach.daily_run.eastmoney_market.fetch_indices", return_value={})
    def test_render_market_lines_holdings_sectors_only(self, _mock_fetch):
        report = WeeklyReport(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=102000,
            weekly_pnl=2000,
            weekly_pnl_pct=2.0,
            realized_pnl=0,
            sector_snapshot=build_holdings_sector_snapshot(
                [{"code": "688008", "name": "澜起科技", "sector": "半导体", "change_pct": 1.0}]
            ),
        )
        text = "\n".join(_render_market_lines(report))
        assert "市场环境" in text
        assert "宏观要闻" in text
        assert "热门板块" not in text

    @patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[])
    def test_friday_close_holdings_from_manifest(
        self,
        mock_ledger,
        mock_exa,
        snapshot,
        portfolio,
    ):
        portfolio_live = dict(portfolio)
        portfolio_live["holdings"] = [
            {"code": "688008", "name": "澜起科技", "shares": 50, "cost": 250.0},
        ]
        close_manifest = {
            "job": "close",
            "_run_date": "2026-08-07",
            "payload": {
                "symbol_results": [
                    {
                        "code": "688008",
                        "result": {
                            "snapshot": {
                                "code": "688008",
                                "price": 85.0,
                                "portfolio": {
                                    "total": 75000,
                                    "cash": 40000,
                                    "holdings": portfolio["holdings"],
                                },
                            }
                        },
                    },
                ]
            },
        }
        with patch(
            "agent_reach.daily_run.weekly_report._load_week_manifests",
            return_value=[close_manifest],
        ):
            report = generate_weekly_report(
                snapshot,
                {"weekly_report": {"exa_sector_research": False}},
                as_of=date(2026, 8, 9),
                portfolio=portfolio_live,
            )
        codes = {h["code"]: h["shares"] for h in report.holdings}
        assert codes.get("688008") == 100
        assert codes.get("002273") == 300
        md = "\n".join(_render_holdings_lines(report))
        assert "截至 2026-08-07 周五收盘" in md
