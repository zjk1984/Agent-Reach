# -*- coding: utf-8
"""Tests for weekly insights: skill learning and process improvements."""

from datetime import date
from unittest.mock import patch

from agent_reach.daily_run.weekly_insights import (
    SkillLearningItem,
    generate_skill_learning,
    generate_weekly_improvements,
    render_improvements_markdown,
    render_skill_learning_markdown,
    _local_skill_inventory,
)


class TestWeeklyInsights:
    def test_local_skill_inventory(self):
        items = _local_skill_inventory()
        assert any(i["name"] == "daily_run_skill" for i in items)
        assert any(i["type"] == "guide" for i in items)

    @patch("agent_reach.daily_run.weekly_insights.run_skill_research", return_value=[])
    def test_generate_skill_learning(self, mock_exa):
        items, research = generate_skill_learning(
            settings={"weekly_report": {"skill_learning": True, "exa_skill_research": False}},
            hot_sectors=[{"name": "澜起", "sector": "半导体", "change_pct": 3}],
            holdings=[{"name": "澜起科技", "code": "688008"}],
            experience_snippets=["2026-07-10 澜起 MSS=48 — 偏离"],
            manifests=[{"job": "close", "_run_date": "2026-07-10"}],
        )
        assert len(items) >= 2
        assert any("daily_run_skill" in i.title for i in items)
        mock_exa.assert_not_called()

    def test_generate_weekly_improvements_missing_jobs(self):
        items = generate_weekly_improvements(
            settings={"weekly_report": {"process_improvements": True}},
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 10),
            manifests=[{"job": "morning", "_run_date": "2026-07-06"}],
            weekly_pnl=-3000,
            weekly_pnl_pct=-3.0,
            holdings=[{"name": "A", "unrealized_pnl": -6000, "unrealized_pct": -8}],
            watchlist=[],
            trades=[],
            mss_summary=[{"date": "2026-07-06", "job": "morning", "mss_final": 45}] * 6,
            experience_snippets=["2026-07-10 x —", "2026-07-09 y —"],
            hot_sectors=[],
        )
        titles = [i.title for i in items]
        assert any("缺失" in t for t in titles)
        assert any("回撤" in t for t in titles)
        assert any("MSS" in t for t in titles)

    def test_render_markdown_sections(self):
        skill_md = render_skill_learning_markdown(
            [
                SkillLearningItem(
                    title="测试技能",
                    source="local",
                    summary="学习 backtest",
                    action="daily-run backtest",
                )
            ],
            [],
        )
        assert "股市技能学习" in skill_md
        assert "测试技能" in skill_md

        imp_md = render_improvements_markdown([])
        assert "流程改进意见" in imp_md
