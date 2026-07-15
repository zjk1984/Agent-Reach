# -*- coding: utf-8
"""Tests for snapshot builder and schedule helpers."""

import json
from unittest.mock import patch

import pytest

from agent_reach.daily_run.quote_fetch import QuoteFetchResult
from agent_reach.daily_run.schedule import default_entries, render_crontab_block
from agent_reach.daily_run.snapshot_builder import (
    build_snapshot,
    code_to_xueqiu_symbol,
    load_portfolio,
)


@pytest.fixture
def portfolio():
    return {
        "primary_code": "688008",
        "total": 91938,
        "cash_ratio": 0.61,
        "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
        "holdings": [
            {"code": "688008", "name": "澜起科技", "shares": 100, "cost": 255.87},
            {"code": "002273", "name": "水晶光电", "shares": 300, "cost": 33.81},
        ],
        "watchlist": [{"code": "603986", "name": "兆易创新"}],
        "sources_overrides": {
            "flow": {"summary": "北向净流入"},
            "sentiment": {"summary": "DDR5 讨论"},
        },
    }


class TestSnapshotBuilder:
    def test_code_to_xueqiu_symbol(self):
        assert code_to_xueqiu_symbol("688008") == "SH688008"
        assert code_to_xueqiu_symbol("002273") == "SZ002273"

    @patch("agent_reach.daily_run.snapshot_builder.collect_macro_context")
    @patch("agent_reach.daily_run.quote_fetch.fetch_quotes_map")
    def test_build_snapshot_enriched(self, mock_fetch, mock_macro, portfolio):
        mock_macro.return_value = {
            "mss_breakdown": {"fx": 40, "flow": 50, "global": 45, "sentiment": 48},
            "sources": {
                "flow": {"summary": "北向净流入 12 亿"},
                "sentiment": {"summary": "DDR5 讨论"},
            },
            "macro_summary": "live macro",
        }
        mock_fetch.return_value = QuoteFetchResult(
            quotes={
                "688008": {
                    "code": "688008",
                    "name": "澜起科技",
                    "price": 260.0,
                    "change_pct": 1.5,
                    "source": "xueqiu",
                }
            },
            sources_used=["xueqiu"],
        )
        with patch("agent_reach.daily_run.snapshot_builder._attach_technicals") as mock_tech:
            mock_tech.return_value = {
                "code": "688008",
                "name": "澜起科技",
                "price": 260.0,
                "change_pct": 1.5,
                "ma20": 255.0,
                "position_20d": 0.55,
                "volume_ratio": 1.1,
                "source": "xueqiu",
            }
            snap = build_snapshot(portfolio, enrich=True)
        assert snap["code"] == "688008"
        assert snap["price"] == 260.0
        assert snap["quote_fetch"]["coverage_pct"] == 33.3
        assert snap["sources"]["flow"]["summary"] != "待更新"

    def test_build_snapshot_no_enrich(self, portfolio):
        snap = build_snapshot(portfolio, enrich=False)
        assert snap["code"] == "688008"
        assert "price" not in snap


class TestSchedule:
    def test_render_crontab_block(self):
        block = render_crontab_block()
        assert "agent-reach daily-run schedule BEGIN" in block
        assert "Asia/Shanghai" in block
        assert "schedule run morning" in block
        assert "schedule run intraday" in block
        assert "schedule run close" in block

    def test_default_entries_count(self):
        assert len(default_entries()) == 12

    @patch("agent_reach.daily_run.workflows.save_morning_baseline")
    @patch("agent_reach.daily_run.workflows.run_morning")
    @patch("agent_reach.daily_run.snapshot_builder.build_and_save")
    @patch("agent_reach.daily_run.snapshot_builder.load_portfolio")
    def test_run_scheduled_morning(self, mock_load, mock_build, mock_morning, mock_save_baseline, portfolio, tmp_path):
        mock_load.return_value = portfolio
        mock_build.return_value = ({"code": "688008"}, tmp_path / "snap.json")
        mock_morning.return_value = {"snapshot": {"code": "688008"}, "evaluation": {"report": {}}}

        from agent_reach.daily_run.schedule import run_scheduled

        result = run_scheduled("morning", push=False)
        assert result["job"] == "morning"
        mock_save_baseline.assert_called_once()
