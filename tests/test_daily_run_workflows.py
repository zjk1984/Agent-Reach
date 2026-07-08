# -*- coding: utf-8
"""Tests for morning/close one-click workflows."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.workflows import run_close, run_morning, save_morning_baseline


@pytest.fixture
def morning_snapshot():
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "code": "688008",
        "name": "澜起科技",
        "price": 255.87,
        "ma20": 260.0,
        "position_20d": 0.55,
        "volume_ratio": 1.2,
        "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
        "sources": {
            "quote": {"summary": "q"},
            "flow": {"summary": "f"},
            "sentiment": {"summary": "s"},
        },
        "structured_review_complete": True,
    }


class TestMorningWorkflow:
    @patch("agent_reach.daily_run.workflows.push_report")
    @patch("agent_reach.daily_run.workflows._send_start_notification")
    def test_run_morning_dry_pipeline(self, mock_start, mock_push, morning_snapshot):
        result = run_morning(morning_snapshot, settings=load_settings(), push=False, start_notify=False)
        assert "experts" in result["steps"]
        assert "evaluate" in result["steps"]
        assert "push" not in result["steps"]
        mock_push.assert_not_called()
        mock_start.assert_not_called()
        assert result["evaluation"]["report"]["verdict"]

    @patch("agent_reach.daily_run.workflows.push_report", return_value={"code": 0, "data": {}})
    @patch("agent_reach.daily_run.workflows._send_start_notification")
    def test_run_morning_push(self, mock_start, mock_push, morning_snapshot):
        result = run_morning(morning_snapshot, settings=load_settings(), push=True, start_notify=True)
        assert result["steps"] == ["start_notify", "experts", "evaluate", "push"]
        assert mock_push.called
        assert mock_start.called


class TestCloseWorkflow:
    def test_run_close_dry(self, morning_snapshot):
        baseline = dict(morning_snapshot)
        baseline["mss_final"] = 65
        baseline["verdict"] = "可做"
        baseline["mss_range"] = [45, 58]
        current = dict(morning_snapshot)
        current["mss_breakdown"] = {"fx": 35, "flow": 48, "global": 38, "sentiment": 50}
        result = run_close(current, baseline, settings=load_settings(), push=False)
        assert "verify" in result
        assert "Markdown" in result["markdown"] or "验证摘要" in result["markdown"]

    def test_save_baseline(self, morning_snapshot, tmp_path):
        path = save_morning_baseline(morning_snapshot, path=tmp_path / "morning.json")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["code"] == "688008"
