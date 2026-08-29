# -*- coding: utf-8
"""Tests for scoped morning card content (macro headlines, recap, symbol logic)."""

from agent_reach.daily_run.morning_cards import (
    MorningCardContext,
    MorningSymbolRow,
    render_decision_markdown,
    render_holdings_overview_markdown,
    render_morning_card_sections,
    render_xueqiu_hot_markdown,
)
from agent_reach.daily_run.morning_content_scope import (
    collect_macro_headline_candidates,
    infer_affected_sectors,
    infer_impact_label,
    render_domestic_market_brief,
    render_macro_headlines_markdown,
    render_merged_symbol_logic_markdown,
    render_prior_close_recap_markdown,
    render_scoped_morning_narrative_markdown,
    render_symbol_morning_logic_markdown,
    select_macro_headlines,
)

PORTFOLIO = {
    "holdings": [
        {"code": "688008", "name": "澜起科技", "sector": "半导体", "shares": 100, "price": 255.0},
        {"code": "002273", "name": "水晶光电", "sector": "光学", "shares": 300, "price": 34.0},
    ],
}


class TestMacroHeadlines:
    def test_infer_impact_and_sectors(self):
        assert infer_impact_label("半导体存储芯片价格上涨") == "利好"
        assert infer_impact_label("行业调查引发下跌") == "利空"
        assert infer_impact_label("例行会议召开") == "中性"
        sectors = infer_affected_sectors("澜起科技 DDR 涨价", PORTFOLIO)
        assert "半导体" in sectors

    def test_select_macro_headlines_limits_and_prioritizes_holdings(self):
        macro_signals = {
            "hot_topics": [
                {"title": "某国大选结果公布"},
                {"title": "澜起科技所在半导体板块获政策扶持"},
                {"title": "光学镜头出口数据回暖"},
                {"title": "全球石油库存下降"},
                {"title": "水晶光电产业链订单增长"},
            ]
        }
        featured, extra = select_macro_headlines(
            macro_signals=macro_signals,
            sources={},
            portfolio=PORTFOLIO,
            limit=3,
        )
        assert len(featured) == 3
        titles = [row["title"] for row in featured]
        assert any("澜起" in t or "半导体" in t for t in titles)
        assert all("sectors" in row and "impact" in row for row in featured)
        assert len(extra) >= 1

    def test_render_macro_headlines_markdown_format(self):
        featured = [
            {
                "title": "半导体政策利好",
                "sectors": "半导体",
                "impact": "利好",
            }
        ]
        extra = [{"title": "无关宏观新闻", "url": "https://example.com/news"}]
        md = render_macro_headlines_markdown(featured, extra)
        assert "**宏观要闻**" in md
        assert "影响板块：**半导体**" in md
        assert "对持仓影响：**利好**" in md
        assert "**延伸阅读：**" in md

    def test_collect_deduplicates_and_scores(self):
        macro_signals = {
            "hot_topics_matched": [{"title": "澜起科技 DDR 涨价"}],
            "hot_topics": [{"title": "澜起科技 DDR 涨价"}, {"title": "无关新闻"}],
        }
        rows = collect_macro_headline_candidates(
            macro_signals=macro_signals,
            sources={},
            portfolio=PORTFOLIO,
        )
        titles = [r["title"] for r in rows]
        assert titles.count("澜起科技 DDR 涨价") == 1
        assert rows[0]["score"] >= rows[-1]["score"]


class TestMarketBriefAndRecap:
    def test_render_domestic_market_brief_once(self):
        md = render_domestic_market_brief(
            snapshot={"sources": {}},
            macro_signals={"index_change_pct": 0.85, "northbound_flow_yi": 12.3},
        )
        assert md.startswith("**大盘分析**")
        assert "+0.85%" in md
        assert "北向" in md
        assert md.count("大盘分析") == 1

    def test_render_prior_close_recap_markdown(self, monkeypatch):
        from agent_reach.daily_run import morning_content_scope as scope

        class _PnlRow:
            daily_pnl = 1200.0
            daily_pnl_pct = 1.2

        monkeypatch.setattr(scope, "build_prior_close_recap", lambda *_a, **_k: "昨日组合盈亏 **+1,200**（+1.20%） · 昨日收盘以**观察**为主（2/2 只）")
        md = render_prior_close_recap_markdown(PORTFOLIO)
        assert "**昨日收盘要点**" in md
        assert "昨日组合盈亏" in md
        assert "观察" in md


class TestSymbolLogicScope:
    def test_render_symbol_morning_logic_excludes_macro(self):
        report = {
            "code": "688008",
            "name": "澜起科技",
            "verdict": "观察",
            "confidence": "中",
            "mss_final": 48.0,
            "reasoning": "DDR 景气回升支撑估值",
            "invalidation": "跌破 MA20",
            "entry_price": 250.0,
            "stop_loss_price": 240.0,
        }
        md = render_symbol_morning_logic_markdown(report, snapshot={"code": "688008"})
        assert "**个股逻辑：**" in md
        assert "大盘" not in md
        assert "宏观" not in md
        assert "MSS 拆解" not in md

    def test_render_merged_symbol_logic_points_to_overview(self):
        entries = [
            ("澜起科技", "688008", {"verdict": "观察", "confidence": "中", "mss_final": 48, "reasoning": "A", "invalidation": "X"}, {}),
            ("水晶光电", "002273", {"verdict": "回避", "confidence": "低", "mss_final": 32, "reasoning": "B", "invalidation": "Y"}, {}),
        ]
        md = render_merged_symbol_logic_markdown(entries)
        assert "大盘/宏观见持仓速览" in md
        assert "澜起科技" in md
        assert "水晶光电" in md

    def test_render_scoped_narrative_strips_macro_focus(self):
        md = render_scoped_morning_narrative_markdown(
            {
                "summary": "维持观察纪律",
                "focus_points": ["澜起科技订单", "北向资金大幅流入", "大盘指数走弱"],
                "risk_alerts": ["止损位逼近"],
            }
        )
        assert "维持观察纪律" in md
        assert "澜起科技订单" in md
        assert "北向" not in md
        assert "大盘" not in md
        assert "止损位逼近" in md


class TestMorningCardsIntegration:
    def test_overview_includes_scoped_sections(self):
        ctx = MorningCardContext(
            portfolio=PORTFOLIO,
            primary_snapshot={
                "macro_signals": {
                    "index_change_pct": -0.3,
                    "northbound_flow_yi": -5.0,
                    "hot_topics": [
                        {"title": "澜起科技 DDR 景气回升"},
                        {"title": "无关国际新闻"},
                    ],
                },
                "sources": {},
            },
            macro_signals={
                "index_change_pct": -0.3,
                "northbound_flow_yi": -5.0,
                "hot_topics": [
                    {"title": "澜起科技 DDR 景气回升"},
                    {"title": "无关国际新闻"},
                ],
            },
            symbol_rows=[
                MorningSymbolRow(
                    code="688008",
                    name="澜起科技",
                    holding=PORTFOLIO["holdings"][0],
                    report={"verdict": "观察", "mss_final": 48.0},
                    snapshot={},
                )
            ],
            global_markets={
                "as_of_label": "截至 08:00",
                "ok_count": 1,
                "required_count": 1,
                "indices": [],
            },
        )
        md = render_holdings_overview_markdown(ctx)
        assert "**大盘分析**" in md
        assert "**宏观要闻**" in md
        assert "影响板块：" in md
        assert "对持仓影响：" in md
        assert "持仓早盘速览" in md

    def test_decision_card_stock_logic_only(self):
        ctx = MorningCardContext(
            portfolio=PORTFOLIO,
            symbol_rows=[
                MorningSymbolRow(
                    code="688008",
                    name="澜起科技",
                    holding=PORTFOLIO["holdings"][0],
                    report={
                        "verdict": "观察",
                        "confidence": "中",
                        "mss_final": 48.0,
                        "reasoning": "景气回升",
                        "invalidation": "跌破 MA20",
                    },
                    snapshot={"code": "688008"},
                )
            ],
        )
        md = render_decision_markdown(ctx)
        assert "**个股逻辑：**" in md
        assert "北向" not in md
        assert "宏观要闻" not in md

    def test_suppressed_hot_and_eastmoney_cards(self):
        ctx = MorningCardContext(
            portfolio=PORTFOLIO,
            symbol_rows=[
                MorningSymbolRow(
                    code="688008",
                    name="澜起科技",
                    holding=PORTFOLIO["holdings"][0],
                    report={"verdict": "观察", "mss_final": 48.0},
                    snapshot={},
                )
            ],
            global_markets={
                "as_of_label": "截至 08:00",
                "ok_count": 1,
                "required_count": 1,
                "indices": [],
            },
        )
        assert render_xueqiu_hot_markdown(ctx) == ""
        categories = [s.category for s in render_morning_card_sections(ctx)]
        assert "xueqiu_hot" not in categories
        assert "eastmoney" not in categories
