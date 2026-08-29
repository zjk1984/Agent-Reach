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
from agent_reach.daily_run.verify import VerifyResult, merge_verify_forecast_markdown


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

    def test_render_close_sections_includes_forecast_in_verify_and_improvements(self):
        """Forecast review merges into verify; other extras remain separate Feishu cards."""
        sections = render_close_sections(
            verify_name="澜起",
            verify_markdown="**验证**",
            watchlist_adjust_markdown="**观察池调整内容**",
            code_review_markdown="**代码走读内容**",
            forecast_review_markdown="**预测回顾内容**",
            close_improvements_markdown="**改进建议内容**",
            technical_watch_markdown="**技术情景内容**",
        )
        categories = [s.category for s in sections]
        assert "watchlist_adjust" in categories
        assert "code_review" in categories
        assert "forecast_review" not in categories
        assert "close_improvements" in categories
        assert "technical_watch" in categories
        verify = next(s for s in sections if s.category == "verify")
        assert "**验证**" in verify.body
        assert "**预测回顾内容**" in verify.body
        assert categories.index("watchlist_adjust") < categories.index("close_improvements")
        assert categories.index("close_improvements") < categories.index("technical_watch")
        assert categories.index("technical_watch") < categories.index("verify")

    def test_close_sections_from_run_merges_forecast_into_verify(self):
        """Per-symbol merge path carries forecast review inside the verify card."""
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
        assert "forecast_review" not in categories
        verify = next(s for s in sections if s.category == "verify")
        assert "**预测回顾**" in verify.body
        assert "close_improvements" in categories
        assert "watchlist_adjust" in categories
        assert "code_review" in categories

    def test_merge_verify_forecast_drops_duplicate_mss_line(self):
        verify = VerifyResult(
            code="688008",
            name="澜起科技",
            price_baseline=100.0,
            price_current=101.0,
            price_delta_pct=0.01,
            mss_baseline=45.0,
            mss_current=48.0,
            mss_delta=3.0,
            verdict_baseline="观察",
            verdict_current="观察",
            verdict_changed=False,
            mss_range_baseline=(40.0, 52.0),
            mss_within_prediction=True,
            summary="MSS 在预测区间内",
        )
        verify_md = (
            "**验证摘要：** MSS 在预测区间内\n\n"
            "**MSS 预测区间：** [40, 52] → ✅ 命中"
        )
        forecast_md = (
            "**🔮 下周预测复盘（今日）**\n\n"
            "- 标的命中率：**2/3** (67%)\n"
            "- MSS ✅ 预测 45 vs 实际 48\n"
            "- ✅ **澜起科技** 预测 ↑[+1.0%,+3.0%] 实际 +1.50%"
        )
        merged = merge_verify_forecast_markdown(verify_md, forecast_md, verify=verify)
        assert "MSS 预测区间" in merged
        assert "MSS ✅ 预测" not in merged
        assert "标的命中率" in merged

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
