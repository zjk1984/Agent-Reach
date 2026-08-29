# -*- coding: utf-8
"""Tests for morning card layout."""

from agent_reach.daily_run.global_markets_collector import (
    render_global_markets_markdown,
    _failed_index,
    _ok_index,
)
from agent_reach.daily_run.morning_cards import (
    MorningCardContext,
    MorningSymbolRow,
    morning_card_layout_enabled,
    render_decision_markdown,
    render_holdings_overview_markdown,
    render_morning_card_sections,
    _change_vs_prev_close,
    _format_open_cell,
    _position_advice_line,
    _trigger_lines,
)


PORTFOLIO = {
    "total": 100000.0,
    "cash": 40000.0,
    "holdings": [
        {
            "code": "688008",
            "name": "澜起科技",
            "shares": 100,
            "price": 255.0,
            "open": 252.5,
            "prev_close": 250.0,
            "change_pct": 2.0,
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "price": 34.0,
            "open": 0,
            "prev_close": 34.5,
            "volume": 0,
            "turnover": 0,
        },
    ],
}


class TestMorningCardLayout:
    def test_layout_enabled_by_default(self):
        assert morning_card_layout_enabled({}) is True
        assert morning_card_layout_enabled({"report": {"morning_card_layout": "legacy"}}) is False

    def test_global_markets_failure_markdown(self):
        payload = {
            "as_of_label": "截至 08:00",
            "ok_count": 2,
            "required_count": 4,
            "indices": [
                _ok_index("nasdaq", "纳指", {"price": 26402.42, "prev_close": 26541.35, "change_pct": -0.52}),
                _failed_index("dow", "道指"),
            ],
        }
        md = render_global_markets_markdown(payload)
        assert "截至 08:00" in md
        assert "纳指" in md
        assert "⚠️ 数据获取失败" in md
        assert "未使用历史缓存" in md

    def test_open_and_suspended_cells(self):
        holding_open = PORTFOLIO["holdings"][0]
        assert _format_open_cell(holding_open, {}, suspended=False) == "¥252.50"
        suspended = PORTFOLIO["holdings"][1]
        assert _format_open_cell(suspended, suspended, suspended=True) == "🔒 停牌"
        assert _change_vs_prev_close(holding_open, {}, suspended=False).startswith("+2.00%（昨收")

    def test_trigger_and_position_advice(self):
        report = {
            "verdict": "观察",
            "entry_price": 250.0,
            "stop_loss_price": 260.0,
        }
        holding = PORTFOLIO["holdings"][0]
        triggers = _trigger_lines(report, holding, {}, suspended=False)
        assert "✅已触发" in triggers
        assert "250.00" in triggers
        advice = _position_advice_line(
            holding,
            PORTFOLIO,
            {"verdict": "回避"},
            {"mss_final": 30, "verdict": "回避"},
            settings={},
        )
        assert "当前" in advice and "目标" in advice

    def test_render_holdings_overview_card(self):
        ctx = MorningCardContext(
            portfolio=PORTFOLIO,
            primary_snapshot={
                "macro_signals": {
                    "index_change_pct": 0.5,
                    "northbound_flow_yi": 8.0,
                    "hot_topics": [{"title": "澜起科技半导体景气回升"}],
                },
                "sources": {},
            },
            macro_signals={
                "index_change_pct": 0.5,
                "northbound_flow_yi": 8.0,
                "hot_topics": [{"title": "澜起科技半导体景气回升"}],
            },
            symbol_rows=[
                MorningSymbolRow(
                    code="688008",
                    name="澜起科技",
                    holding=PORTFOLIO["holdings"][0],
                    report={"verdict": "观察", "mss_final": 48.0, "entry_price": 250.0, "stop_loss_price": 240.0},
                    snapshot={},
                ),
                MorningSymbolRow(
                    code="002273",
                    name="水晶光电",
                    holding=PORTFOLIO["holdings"][1],
                    report={"verdict": "回避", "mss_final": 32.0},
                    snapshot={},
                ),
            ],
            global_markets={
                "as_of_label": "截至 08:00",
                "ok_count": 4,
                "required_count": 4,
                "indices": [
                    _ok_index("nasdaq", "纳指", {"price": 26402.42, "prev_close": 26541.35, "change_pct": -0.52}),
                ],
            },
        )
        md = render_holdings_overview_markdown(ctx)
        assert "持仓早盘速览" in md
        assert "澜起科技" in md
        assert "125.30" not in md  # different fixture
        assert "截至 08:00" in md
        assert "**大盘分析**" in md
        assert "**宏观要闻**" in md
        assert "影响板块：" in md
        assert "对持仓影响：" in md
        assert "| 股票 | 昨收 | 今开 | 涨跌幅 | 成交量比 | MSS | 标签 |" in md

    def test_decision_card_no_market_analysis(self):
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
                        "reasoning": "DDR 景气",
                        "invalidation": "跌破 MA20",
                    },
                    snapshot={"code": "688008"},
                )
            ],
        )
        md = render_decision_markdown(ctx)
        assert "**个股逻辑：**" in md
        assert "**大盘分析**" not in md
        assert "宏观要闻" not in md

    def test_render_morning_card_sections_order(self):
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
                "indices": [_ok_index("nasdaq", "纳指", {"price": 1.0, "prev_close": 1.0, "change_pct": 0.0})],
            },
            team_markdown="**专家** 一致看多",
        )
        sections = render_morning_card_sections(ctx)
        assert sections[0].category == "action_checklist"
        assert sections[0].title.startswith("📋 今日操作清单 1/")
        assert sections[1].category == "holdings_overview"
        assert [s.category for s in sections if s.category == "experts"]
