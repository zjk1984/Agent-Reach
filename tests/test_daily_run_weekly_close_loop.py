# -*- coding: utf-8
"""Tests for weekly report ↔ daily close card data loop."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.daily_run.weekly_close_loop import (
    aggregate_close_card_trades,
    build_close_loop_position_change,
    load_outlook_plan_for_backtrack,
    merge_weekly_trade_sources,
    render_outlook_backtrack_markdown,
    resolve_friday_close_portfolio,
    save_weekly_outlook_plan,
    summarize_close_card_predictions,
    verify_outlook_plan_execution,
)
from agent_reach.daily_run.weekly_content_scope import render_weekly_prediction_verify_markdown
from agent_reach.daily_run.weekly_report import generate_weekly_report, render_weekly_sections


def _close_manifest(
    day: str,
    *,
    stock_ratio: float = 0.6,
    position_change: str = "无调仓",
    trades: list | None = None,
    forecast: dict | None = None,
) -> dict:
    ps = {
        "end_total": 100000,
        "stock_mv": 100000 * stock_ratio,
        "cash": 100000 * (1 - stock_ratio),
        "stock_ratio": stock_ratio,
        "cash_ratio": 1 - stock_ratio,
        "position_change": position_change,
        "holdings": [
            {
                "code": "688008",
                "name": "澜起科技",
                "shares": 100,
                "price": 260.0,
                "week_chg": 500.0,
            }
        ],
    }
    if trades:
        ps["trades"] = trades
    payload_result: dict = {"portfolio_summary": ps}
    if forecast:
        payload_result["forecast_review"] = forecast
    return {
        "_run_date": day,
        "job": "close",
        "payload": {"result": payload_result},
    }


class TestCloseCardTradeAggregation:
    def test_aggregate_mon_to_fri_trades(self):
        manifests = [
            _close_manifest(
                "2026-08-04",
                trades=[
                    {
                        "at": "2026-08-04T07:30:00+00:00",
                        "actions": [
                            {
                                "side": "buy",
                                "code": "688008",
                                "name": "澜起科技",
                                "shares": 100,
                                "price": 250.0,
                                "amount": 25000.0,
                            }
                        ],
                    }
                ],
            ),
            _close_manifest(
                "2026-08-05",
                trades=[
                    {
                        "at": "2026-08-05T07:30:00+00:00",
                        "actions": [
                            {
                                "side": "sell",
                                "code": "002273",
                                "name": "水晶光电",
                                "shares": 200,
                                "price": 30.0,
                                "amount": 6000.0,
                                "realized_pnl": 200.0,
                            }
                        ],
                    }
                ],
            ),
        ]
        rows = aggregate_close_card_trades(
            manifests,
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
        )
        assert len(rows) == 2
        assert rows[0]["source"] == "close_card"
        assert "收盘卡片" in rows[0]["close_ref"]
        assert rows[0]["side"] == "买"
        assert rows[1]["side"] == "卖"

    def test_merge_prefers_close_card(self):
        close_rows = [
            {
                "date": "2026-08-04",
                "code": "688008",
                "side_raw": "buy",
                "shares": 100,
                "price": 250.0,
                "source": "close_card",
            }
        ]
        ledger_rows = [
            {
                "date": "2026-08-04",
                "code": "688008",
                "side_raw": "buy",
                "shares": 100,
                "price": 250.0,
                "source": "ledger",
            },
            {
                "date": "2026-08-06",
                "code": "002273",
                "side_raw": "sell",
                "shares": 50,
                "price": 28.0,
                "source": "ledger",
            },
        ]
        merged = merge_weekly_trade_sources(close_rows, ledger_rows)
        assert len(merged) == 2
        assert merged[0]["source"] == "close_card"
        assert merged[1]["source"] == "ledger"


class TestFridayHoldings:
    def test_resolve_friday_close_portfolio(self):
        pf = {"holdings": [{"code": "002273", "shares": 100}], "cash": 50000}
        end_record = _close_manifest("2026-08-08", stock_ratio=0.55)
        resolved, holdings, source = resolve_friday_close_portfolio(end_record, pf)
        assert holdings[0]["code"] == "688008"
        assert "周五收盘卡片" in source


class TestCloseLoopPredictions:
    def test_daily_rows_in_prediction_summary(self):
        forecast = {
            "symbol_evals": [
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "predicted_direction": "up",
                    "actual_change_pct": 1.5,
                    "hit": True,
                }
            ],
            "mss_hit": True,
        }
        data = summarize_close_card_predictions(
            [_close_manifest("2026-08-05", forecast=forecast)],
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
        )
        assert data.get("source") == "close_card"
        assert len(data.get("daily_rows") or []) == 1
        md = "\n".join(render_weekly_prediction_verify_markdown(data))
        assert "每日收盘卡片预测验证" in md


class TestPositionChangeLoop:
    def test_daily_notes_from_close_cards(self):
        manifests = [
            _close_manifest("2026-08-04", stock_ratio=0.55, position_change="加仓澜起科技"),
            _close_manifest("2026-08-08", stock_ratio=0.62, position_change="无调仓"),
        ]
        summary = build_close_loop_position_change(
            manifests,
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_record=manifests[0],
            end_record=manifests[1],
            close_trades=[],
        )
        assert summary["start_exposure_pct"] == 55.0
        assert summary["end_exposure_pct"] == 62.0
        assert any("加仓" in n for n in summary["daily_notes"])


class TestOutlookBacktrack:
    def test_save_load_and_verify(self, tmp_path, monkeypatch):
        outlook_dir = tmp_path / "weekly_outlook"
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_close_loop._OUTLOOK_DIR",
            outlook_dir,
        )
        plan = {
            "operation_plan": [
                {"code": "688008", "name": "澜起科技", "action": "买入", "trigger": "突破 MA20"},
                {"code": "002273", "name": "水晶光电", "action": "持有", "trigger": "—"},
            ],
            "risk_calendar": [],
        }
        save_weekly_outlook_plan(
            week_end=date(2026, 8, 1),
            week_start=date(2026, 7, 28),
            next_week_outlook=plan,
            target_week_start=date(2026, 8, 4),
            target_week_end=date(2026, 8, 8),
        )
        loaded = load_outlook_plan_for_backtrack(date(2026, 8, 4))
        assert loaded is not None
        assert loaded["target_week_start"] == "2026-08-04"

        target_manifests = [
            _close_manifest(
                "2026-08-05",
                trades=[
                    {
                        "at": "2026-08-05T07:30:00+00:00",
                        "actions": [
                            {
                                "side": "buy",
                                "code": "688008",
                                "name": "澜起科技",
                                "shares": 100,
                                "price": 250.0,
                                "amount": 25000.0,
                            }
                        ],
                    }
                ],
            )
        ]
        backtrack = verify_outlook_plan_execution(
            loaded,
            manifests=target_manifests,
            holdings=[{"code": "688008", "week_chg": 800.0}],
        )
        assert backtrack["total_count"] == 2
        assert backtrack["executed_count"] >= 1
        md = "\n".join(render_outlook_backtrack_markdown(backtrack))
        assert "计划执行回溯" in md
        assert "澜起科技" in md

    def test_synthesize_outlook_plan_when_file_missing(self, tmp_path, monkeypatch):
        outlook_dir = tmp_path / "weekly_outlook"
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_close_loop._OUTLOOK_DIR",
            outlook_dir,
        )
        from agent_reach.daily_run.weekly_close_loop import synthesize_outlook_plan_for_backtrack

        plan = synthesize_outlook_plan_for_backtrack(
            date(2026, 8, 24),
            date(2026, 8, 28),
            holdings=[
                {"code": "688008", "name": "澜起科技", "market_value": 20000},
            ],
        )
        assert plan is not None
        assert plan["target_week_start"] == "2026-08-24"
        assert plan.get("operation_plan")


class TestGenerateWeeklyReportCloseLoop:
    @patch("agent_reach.daily_run.weekly_report._load_trade_ledger_range", return_value=[])
    @patch("agent_reach.daily_run.weekly_report.run_sector_research", return_value=[])
    @patch("agent_reach.daily_run.weekly_report._load_week_manifests")
    def test_close_loop_fields_populated(
        self,
        mock_manifests,
        mock_exa,
        mock_ledger,
        tmp_path,
        monkeypatch,
    ):
        outlook_dir = tmp_path / "weekly_outlook"
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_close_loop._OUTLOOK_DIR",
            outlook_dir,
        )
        save_weekly_outlook_plan(
            week_end=date(2026, 7, 25),
            week_start=date(2026, 7, 21),
            next_week_outlook={
                "operation_plan": [{"code": "688008", "name": "澜起科技", "action": "持有"}],
            },
            target_week_start=date(2026, 7, 28),
            target_week_end=date(2026, 8, 1),
        )

        mock_manifests.return_value = [
            _close_manifest(
                "2026-08-04",
                stock_ratio=0.58,
                position_change="买入澜起科技",
                trades=[
                    {
                        "at": "2026-08-04T07:30:00+00:00",
                        "actions": [
                            {
                                "side": "buy",
                                "code": "688008",
                                "name": "澜起科技",
                                "shares": 100,
                                "price": 250.0,
                                "amount": 25000.0,
                            }
                        ],
                    }
                ],
                forecast={
                    "symbol_evals": [
                        {
                            "code": "688008",
                            "name": "澜起科技",
                            "predicted_direction": "up",
                            "actual_change_pct": 1.0,
                            "hit": True,
                        }
                    ],
                    "mss_hit": True,
                },
            ),
            _close_manifest("2026-08-08", stock_ratio=0.62),
        ]
        portfolio = {
            "total": 100000,
            "cash": 40000,
            "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "cost": 250.0}],
        }
        snapshot = {"portfolio": portfolio, "code": "688008", "name": "澜起科技", "price": 260.0}
        report = generate_weekly_report(
            snapshot,
            {"weekly_report": {}},
            as_of=date(2026, 8, 9),
            portfolio=portfolio,
        )
        assert report.trade_log
        assert report.trade_log[0]["source"] == "close_card"
        assert report.prediction_verification.get("daily_rows")
        assert report.position_change.get("daily_notes")
        assert "收盘卡片" in (report.close_loop_meta or {}).get("trade_source_note", "")
        labels = [s.label for s in render_weekly_sections(report)]
        if report.outlook_backtrack.get("rows"):
            assert "计划回溯" in labels
