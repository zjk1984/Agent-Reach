# -*- coding: utf-8
"""Tests for per-symbol news vs portfolio macro/hot card separation."""

from agent_reach.daily_run.pipeline import render_markdown, render_symbol_decision_markdown
from agent_reach.daily_run.report_narrative import (
    _close_deterministic,
    _morning_deterministic,
    build_morning_context,
)
from agent_reach.daily_run.report_push import ReportSection, merge_sections_by_category, render_merged_decision_markdown
from agent_reach.daily_run.symbol_news import render_symbol_news_markdown, symbol_news_summary


SNAPSHOT = {
    "code": "688008",
    "name": "澜起科技",
    "macro_summary": "大盘 +1.2%；北向 +10亿",
    "macro_signals": {
        "portfolio_hot_stocks": [
            {"code": "688008", "name": "澜起科技", "board": "人气榜", "rank": 3, "role": "holding"},
            {"code": "002273", "name": "水晶光电", "board": "人气榜", "rank": 8, "role": "holding"},
        ],
        "portfolio_hot_posts": [
            {
                "title": "澜起科技业绩超预期",
                "matched_keywords": ["澜起科技"],
            },
            {
                "title": "水晶光电光学景气",
                "matched_keywords": ["水晶光电"],
            },
        ],
        "portfolio_symbol_sentiment": [
            {
                "code": "688008",
                "name": "澜起科技",
                "posts": [{"title": "DDR5 需求强", "author": "u1"}],
            }
        ],
    },
    "watchlist_intel": {
        "688008": {
            "code": "688008",
            "name": "澜起科技",
            "announcements": [{"title": "半年报预增"}],
            "news": [],
            "sentiment": "positive",
        }
    },
}


REPORT = {
    "code": "688008",
    "name": "澜起科技",
    "verdict": "观察",
    "confidence": "中",
    "mss_final": 42.0,
    "reasoning": "存储链偏强",
    "invalidation": "跌破 MA20",
    "audit_summary": "通过",
    "macro_summary": "大盘 +1.2%；北向 +10亿",
}


class TestSymbolNewsMarkdown:
    def test_symbol_news_filters_other_holdings(self):
        md = render_symbol_news_markdown("688008", SNAPSHOT)
        assert "澜起科技" in md
        assert "水晶光电" not in md
        assert "DDR5" in md or "半年报" in md or "业绩超预期" in md

    def test_symbol_news_summary_scoped(self):
        summary = symbol_news_summary("002273", SNAPSHOT)
        assert "水晶光电" in summary or "002273" in summary
        assert "澜起科技" not in summary


class TestSymbolDecisionMarkdown:
    def test_render_symbol_decision_omits_macro_block(self):
        md = render_symbol_decision_markdown(REPORT, snapshot=SNAPSHOT)
        assert "**宏观摘要：**" not in md
        assert "**持仓：**" not in md
        assert "澜起科技" in md
        assert "相关资讯" in md

    def test_render_markdown_still_includes_macro(self):
        md = render_markdown(REPORT)
        assert "**宏观摘要：**" in md


class TestMergedDecisionMarkdown:
    def test_merged_decision_has_no_bottom_macro(self):
        entries = [
            ("澜起科技", "688008", REPORT, SNAPSHOT),
            ("水晶光电", "002273", {**REPORT, "code": "002273", "name": "水晶光电"}, SNAPSHOT),
        ]
        md = render_merged_decision_markdown(entries, report_kind="morning")
        assert "**宏观摘要**" not in md
        assert "688008" in md
        assert "相关资讯" in md

    def test_single_entry_uses_symbol_decision_renderer(self):
        md = render_merged_decision_markdown([("澜起科技", "688008", REPORT, SNAPSHOT)])
        assert "**宏观摘要：**" not in md
        assert "相关资讯" in md


class TestMergePortfolioWideOnce:
    def test_close_market_only_once_in_merge(self):
        g1 = [ReportSection("close_market", "", "宏观A")]
        g2 = [ReportSection("close_market", "", "宏观B")]
        merged = merge_sections_by_category(
            [("澜起科技", g1), ("水晶光电", g2)],
            report_kind="close",
        )
        assert len(merged) == 1
        assert merged[0].body == "宏观A"
        assert "宏观B" not in merged[0].body


class TestSymbolNarrativeScope:
    def test_morning_symbol_context_scoped(self):
        ctx = build_morning_context(SNAPSHOT, REPORT)
        assert ctx.get("portfolio_scope") == "symbol"
        assert ctx.get("symbol_news_summary")

    def test_morning_deterministic_skips_portfolio_hot(self):
        ctx = build_morning_context(SNAPSHOT, REPORT)
        out = _morning_deterministic(ctx)
        focus = " ".join(out.get("focus_points") or [])
        assert "热股" not in focus or "澜起" in focus
        assert "水晶光电" not in focus

    def test_close_deterministic_skips_portfolio_hot(self):
        ctx = {
            "portfolio_scope": "symbol",
            "name": "澜起科技",
            "code": "688008",
            "verify_summary": "验证通过",
            "portfolio_hot_stock_summary": "热股命中：水晶光电#8 · 澜起科技#3",
            "xueqiu_hot_summary": "雪球热门跨组合摘要",
            "symbol_news_summary": "澜起科技：公告：半年报预增",
        }
        out = _close_deterministic(ctx)
        focus = " ".join(out.get("focus_points") or [])
        assert "水晶光电" not in focus
        assert "澜起" in focus or "半年报" in focus
