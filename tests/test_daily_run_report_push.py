# -*- coding: utf-8
"""Tests for split Feishu push (morning / close)."""

from unittest.mock import patch

from agent_reach.daily_run.report_push import (
    close_sections_from_run,
    push_report_sections,
    render_close_sections,
    render_morning_sections,
    split_push_enabled,
)
from agent_reach.daily_run.settings import load_settings


class TestReportPush:
    def test_render_morning_sections(self):
        sections = render_morning_sections(
            team_markdown="**Team**",
            report_markdown="**Decision**",
            report={"name": "澜起", "verdict": "可做"},
        )
        assert len(sections) == 2
        assert sections[0].category == "experts"
        assert sections[0].title == "🌅 早盘 1/2 · 专家共识 · 澜起"
        assert sections[1].category == "decision"
        assert "2/2" in sections[1].title
        assert "可做" in sections[1].title

    def test_render_close_sections_skips_empty(self):
        sections = render_close_sections(
            verify_name="澜起",
            market_markdown="**Market**",
            verify_markdown="**验证**",
        )
        assert len(sections) == 2
        assert sections[0].category == "close_market"
        assert sections[1].category == "verify"

    def test_render_close_sections_empty_market(self):
        sections = render_close_sections(
            verify_name="澜起",
            verify_markdown="**验证**",
        )
        assert len(sections) == 1
        assert sections[0].category == "verify"

    def test_render_close_sections_includes_forecast_review_and_improvements(self):
        """forecast_review/improvements/watchlist/code_review must reach Feishu, not just CLI markdown."""
        sections = render_close_sections(
            verify_name="澜起",
            verify_markdown="**验证**",
            watchlist_adjust_markdown="**观察池调整内容**",
            code_review_markdown="**代码走读内容**",
            forecast_review_markdown="**预测回顾内容**",
            close_improvements_markdown="**改进建议内容**",
        )
        categories = [s.category for s in sections]
        assert "watchlist_adjust" in categories
        assert "code_review" in categories
        assert "forecast_review" in categories
        assert "close_improvements" in categories
        # research -> extras -> experience/verify ordering (mirrors run_close's combined markdown join order)
        assert categories.index("watchlist_adjust") < categories.index("forecast_review")
        assert categories.index("forecast_review") < categories.index("close_improvements")
        assert categories.index("close_improvements") < categories.index("verify")

    def test_close_sections_from_run_includes_forecast_review(self):
        """Per-symbol merge path (close_sections_from_run) must also carry the new markdown fields."""
        run_result = {
            "snapshot": {"macro_signals": {}},
            "verify_markdown": "**验证**",
            "forecast_review_markdown": "**预测回顾**",
            "close_improvements_markdown": "**改进建议**",
            "watchlist_adjust_markdown": "**观察池调整**",
            "code_review_markdown": "**代码走读**",
        }
        sections = close_sections_from_run(run_result, verify_name="澜起")
        categories = [s.category for s in sections]
        assert "forecast_review" in categories
        assert "close_improvements" in categories
        assert "watchlist_adjust" in categories
        assert "code_review" in categories

    def test_split_push_enabled(self):
        cfg = {"report": {"split_push": True, "morning_split_push": False}}
        assert split_push_enabled(cfg, report_kind="morning") is False
        assert split_push_enabled(cfg, report_kind="close") is True

    @patch("agent_reach.integrations.feishu.send_card")
    def test_push_report_sections_split(self, mock_send):
        mock_send.return_value = {"code": 0}
        settings = load_settings()
        settings.setdefault("report", {})["split_push"] = True
        settings["report"]["split_push_interval_seconds"] = 0
        sections = render_morning_sections(
            team_markdown="A",
            report_markdown="B",
            report={"name": "X", "verdict": "观察"},
        )
        out = push_report_sections(
            sections,
            settings=settings,
            config=None,
            report_type="premarket",
            fallback_title="test",
            split=True,
        )
        assert out["mode"] == "split"
        assert out["count"] == 2
        assert mock_send.call_count == 2

    @patch("agent_reach.integrations.feishu.send_card")
    def test_push_report_sections_single_when_disabled(self, mock_send):
        mock_send.return_value = {"code": 0}
        settings = load_settings()
        sections = render_morning_sections(
            team_markdown="A",
            report_markdown="B",
            report={"name": "X", "verdict": "观察"},
        )
        out = push_report_sections(
            sections,
            settings=settings,
            config=None,
            report_type="premarket",
            fallback_title="test",
            split=False,
        )
        assert out["mode"] == "single"
        assert mock_send.call_count == 1
