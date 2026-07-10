# -*- coding: utf-8
"""Tests for snapshot builder and schedule helpers."""

import json
from unittest.mock import patch

import pytest

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
    @patch("agent_reach.daily_run.snapshot_builder.fetch_quotes_map")
    def test_build_snapshot_enriched(self, mock_fetch, mock_macro, portfolio):
        mock_macro.return_value = {
            "mss_breakdown": {"fx": 40, "flow": 50, "global": 45, "sentiment": 48},
            "sources": {
                "flow": {"summary": "北向净流入 12 亿"},
                "sentiment": {"summary": "DDR5 讨论"},
            },
            "macro_summary": "live macro",
        }
        mock_fetch.return_value = {
            "688008": {
                "code": "688008",
                "name": "澜起科技",
                "price": 260.0,
                "change_pct": 1.5,
                "source": "xueqiu",
            }
        }
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
        assert "0 7 * * 1-5" in block or "0 7" in block
        assert "schedule run intraday" in block
        assert "schedule run close" in block

    def test_default_entries_count(self):
        assert len(default_entries()) == 15

    @patch("agent_reach.daily_run.trade_calendar.is_trading_day", return_value=(True, ""))
    @patch("agent_reach.daily_run.intraday.load_state")
    @patch("agent_reach.daily_run.pipeline.evaluate_snapshot")
    @patch("agent_reach.daily_run.intraday.record_scan_from_evaluation")
    @patch("agent_reach.daily_run.workflows.save_morning_baseline")
    @patch("agent_reach.daily_run.workflows.run_morning")
    @patch("agent_reach.daily_run.snapshot_builder.build_and_save")
    @patch("agent_reach.daily_run.snapshot_builder.load_portfolio")
    def test_run_scheduled_morning(
        self,
        mock_load,
        mock_build,
        mock_morning,
        mock_save_baseline,
        mock_record_scan,
        mock_evaluate_snapshot,
        mock_load_state,
        portfolio,
        tmp_path,
    ):
        from agent_reach.daily_run.intraday import IntradayState

        mock_load.return_value = portfolio
        mock_build.return_value = ({"code": "688008"}, tmp_path / "snap.json")
        mock_load_state.return_value = IntradayState(date="2026-07-10", scans=[], trades=[])
        mock_evaluate_snapshot.return_value = {
            "report": {"mss_final": 51, "as_of": "2026-07-10T00:00:00+00:00"},
            "audit": __import__(
                "agent_reach.daily_run.auditor", fromlist=["AuditResult"]
            ).AuditResult(passed=True),
        }
        mock_morning.return_value = {
            "snapshot": {"code": "688008"},
            "evaluation": {"report": {"mss_final": 48}, "audit": __import__(
                "agent_reach.daily_run.auditor", fromlist=["AuditResult"]
            ).AuditResult(passed=True)},
            "steps": [],
        }
        mock_record_scan.side_effect = [
            {"scan": {"scan_id": "S1", "source": "premarket"}},
            {"scan": {"scan_id": "S2", "source": "morning"}},
        ]

        from agent_reach.daily_run.schedule import run_scheduled

        result = run_scheduled("morning", push=False)
        assert result["job"] == "morning"
        mock_save_baseline.assert_called_once()
        assert mock_record_scan.call_count == 2
        assert mock_record_scan.call_args_list[0].kwargs.get("source") == "premarket"
        assert mock_record_scan.call_args_list[1].kwargs.get("source") == "morning"
        assert result["result"]["scan"]["scan"]["scan_id"] == "S2"
        assert "scan_s1_backfill" in result["result"]["steps"]

    @patch("agent_reach.daily_run.trade_calendar.is_trading_day", return_value=(True, ""))
    @patch("agent_reach.daily_run.workflows.run_close")
    @patch("agent_reach.daily_run.workflows.prepare_close_run")
    @patch("agent_reach.daily_run.workflows.load_morning_baseline")
    @patch("agent_reach.daily_run.intraday.load_state")
    @patch("agent_reach.daily_run.snapshot_builder.build_and_save")
    @patch("agent_reach.daily_run.snapshot_builder.load_portfolio")
    def test_run_scheduled_close(
        self,
        mock_load_portfolio,
        mock_build,
        mock_load_state,
        mock_load_baseline,
        mock_prepare_close,
        mock_run_close,
        portfolio,
        tmp_path,
    ):
        from agent_reach.daily_run.intraday import IntradayState

        mock_load_portfolio.return_value = portfolio
        snap = {"code": "688008", "mss_final": 48}
        mock_build.return_value = (snap, tmp_path / "close.json")
        mock_load_state.return_value = IntradayState(
            date="2026-07-10",
            scans=[{"scan_id": "S1", "mss_final": 50}, {"scan_id": "S2", "mss_final": 48}],
            trades=[],
        )
        mock_load_baseline.return_value = {"code": "688008", "mss_final": 52, "mss_range": [45, 55]}
        mock_prepare_close.return_value = {
            "snapshot": snap,
            "portfolio": portfolio,
            "pre_verify": {"verdict_current": "观察"},
            "watchlist_adjust": {"applied": False, "message": "观察池无变更", "changes": []},
            "code_review": {"findings": [], "fixes_applied": [], "portfolio_changed": False},
            "steps": ["pre_verify", "code_review"],
        }
        mock_run_close.return_value = {"verify": {}, "markdown": "close"}

        from agent_reach.daily_run.schedule import run_scheduled

        result = run_scheduled("close", push=False)
        assert result["job"] == "close"
        mock_prepare_close.assert_called_once()
        mock_run_close.assert_called_once()
        assert snap.get("intraday_scans")
        assert result["result"]["code_review"] is not None
        assert result["result"]["prepare_steps"] == ["pre_verify", "code_review"]


class TestRunManifest:
    def test_save_run_manifest_serializes_audit_result(self, tmp_path, monkeypatch):
        from agent_reach.daily_run.auditor import AuditResult
        from agent_reach.daily_run.run_manifest import save_run_manifest

        monkeypatch.setattr(
            "agent_reach.daily_run.run_manifest.runs_dir",
            lambda: tmp_path,
        )
        audit = AuditResult(passed=True, issues=[], warnings=["warn"])
        path = save_run_manifest(
            "intraday",
            {"evaluation": {"audit": audit, "report": {"verdict": "观察"}}},
            duration_ms=12.5,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["payload"]["evaluation"]["audit"]["passed"] is True
        assert data["payload"]["evaluation"]["audit"]["warnings"] == ["warn"]
