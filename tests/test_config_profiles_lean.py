# -*- coding: utf-8
"""Prod profile overlays: fund_lean deep-merge smoke."""

from __future__ import annotations

import json
from pathlib import Path

from agent_reach.daily_run.berkshire.news_pulse import news_pulse_workflow_enabled
from agent_reach.daily_run.findskills_client import run_findskills_queries
from agent_reach.daily_run.settings import load_settings


def _deep_merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = v
    return a


def _merged_lean_settings() -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    base = load_settings(repo_root / "config" / "daily_run_settings.json")
    prof = json.loads((repo_root / "config/profiles/fund_lean.json").read_text())
    return _deep_merge(base, prof)


class TestFundLeanProfile:
    def test_profile_json_loads_and_merge_keys(self):
        settings = _merged_lean_settings()
        assert settings["findskills"]["enabled"] is False
        assert settings["berkshire"]["news_pulse"]["workflows"] == ["weekly"]
        assert settings["plugins"]["exa_research_on_close"] is False
        assert settings["watchlist"]["hot_topic_adjust_enabled"] is False
        assert settings["hot_news"]["platforms"] == ["60s", "weibo"]
        assert settings["weekly_report"]["skill_learning"] is False

    def test_findskills_disabled_returns_empty(self):
        settings = _merged_lean_settings()
        out = run_findskills_queries([{"query": "test", "label": "t"}], settings=settings)
        assert out == []

    def test_news_pulse_daily_workflows_off_weekly_on(self):
        settings = _merged_lean_settings()
        for wf in ("morning", "midday", "close", "forecast"):
            assert news_pulse_workflow_enabled(wf, settings) is False
        assert news_pulse_workflow_enabled("weekly", settings) is True

    def test_berkshire_audit_and_checklist_unchanged(self):
        settings = _merged_lean_settings()
        audit = settings["berkshire"]["report_audit"]
        assert audit.get("enabled") is True
        checklist = settings["berkshire"]["investment_checklist"]
        assert checklist.get("enabled") is True
        assert checklist.get("block_buy_on_fail") is True