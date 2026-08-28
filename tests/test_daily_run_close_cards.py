# -*- coding: utf-8
"""Tests for six-card close Feishu layout."""

from agent_reach.daily_run.close_cards import (
    CLOSE_CARD_ORDER,
    CloseCardContext,
    close_card_layout_enabled,
    render_close_card_sections,
    render_close_summary_markdown,
    render_forecast_verify_markdown,
    render_holdings_detail_markdown,
    render_tomorrow_focus_markdown,
)


PORTFOLIO_SUMMARY = {
    "daily_pnl": 1250.0,
    "daily_pnl_pct": 1.2,
    "cash_ratio": 0.42,
    "reason_lines": ["验证结论 **观察**，观察池 5 只"],
    "holdings": [
        {
            "code": "688008",
            "name": "澜起科技",
            "shares": 100,
            "price": 255.0,
            "change_pct": 1.5,
            "sector": "半导体",
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "price": 34.0,
            "change_pct": -0.8,
            "sector": "光学",
        },
    ],
    "watchlist": [
        {"code": "603986", "name": "兆易创新"},
        {"code": "300308", "name": "中际旭创"},
    ],
    "sector_weights": [{"sector": "半导体", "weight_pct": 55.0}],
}

SYMBOL_ROWS = [
    {
        "code": "688008",
        "name": "澜起科技",
        "price": 255.0,
        "change_pct": 1.5,
        "mss": 48.0,
        "verdict": "观察",
        "shares": 100,
        "role": "持仓",
        "verify": {"price_delta_pct": 0.015, "mss_delta": 2.0, "recommendations": ["守住 MA20"]},
    },
    {
        "code": "300308",
        "name": "中际旭创",
        "price": 120.0,
        "change_pct": -2.1,
        "mss": 38.0,
        "verdict": "回避",
        "shares": 0,
        "role": "观察池",
        "verify": {"price_delta_pct": -0.021, "mss_delta": -4.0},
    },
]


class TestCloseCardLayout:
    def test_layout_enabled_by_default(self):
        assert close_card_layout_enabled({}) is True
        assert close_card_layout_enabled({"report": {"close_card_layout": "legacy"}}) is False

    def test_render_close_card_sections_order(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            symbol_rows=SYMBOL_ROWS,
            verify_by_code={"688008": SYMBOL_ROWS[0]["verify"], "300308": SYMBOL_ROWS[1]["verify"]},
            forecast_review={
                "symbol_hits": 2,
                "symbol_total": 4,
                "accuracy": 0.5,
                "symbol_evals": [
                    {
                        "code": "688008",
                        "predicted_direction": "up",
                        "predicted_range": [0.5, 2.0],
                        "actual_change_pct": 1.5,
                        "hit": True,
                    }
                ],
            },
            market_review={
                "indices": {"000300": {"name": "沪深300", "change_pct": 0.4}},
                "comparison": {"vs_yesterday": {"limit_up_delta": 5, "limit_down_delta": -2, "northbound_delta_yi": 3.2}},
            },
            technical_scenarios=[
                {
                    "scenario_type": "upper_shadow",
                    "name": "中际旭创",
                    "code": "300308",
                    "session_high": 125.0,
                    "session_low": 118.0,
                    "bearish": {"label": "跌破 118 减仓"},
                    "bullish": {"label": "反包 125 可观望"},
                }
            ],
        )
        sections = render_close_card_sections(ctx)
        assert len(sections) == len(CLOSE_CARD_ORDER)
        assert [s.category for s in sections] == list(CLOSE_CARD_ORDER)
        assert sections[0].title.startswith("📊 收盘摘要 1/")
        assert sections[2].title.startswith("🔮 预测验证")

    def test_summary_contains_pnl_and_table(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            symbol_rows=SYMBOL_ROWS,
            market_review={"indices": {"000300": {"name": "沪深300", "change_pct": 0.4}}},
        )
        md = render_close_summary_markdown(ctx)
        assert "当日盈亏" in md
        assert "澜起科技" in md
        assert "风控" in md

    def test_holdings_detail_table(self):
        ctx = CloseCardContext(portfolio_summary=PORTFOLIO_SUMMARY, symbol_rows=SYMBOL_ROWS)
        md = render_holdings_detail_markdown(ctx)
        assert "| 澜起科技 |" in md
        assert "48.0" in md

    def test_forecast_verify_table(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            symbol_rows=SYMBOL_ROWS,
            forecast_review={"symbol_hits": 1, "symbol_total": 2, "accuracy": 0.5, "symbol_evals": []},
        )
        md = render_forecast_verify_markdown(ctx)
        assert "周预测命中率" in md
        assert "| 标的 |" in md

    def test_tomorrow_focus_from_verify_and_technical(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            symbol_rows=SYMBOL_ROWS,
            verify_by_code={"688008": SYMBOL_ROWS[0]["verify"]},
            technical_scenarios=[
                {
                    "scenario_type": "liquidity_shrink",
                    "name": "澜起科技",
                    "code": "688008",
                    "session_close": 255.0,
                    "bullish": {"label": "放量收复 260"},
                    "bearish": {"label": "跌破 250 减仓"},
                }
            ],
        )
        md = render_tomorrow_focus_markdown(ctx)
        assert "守住 MA20" in md
        assert "250" in md or "260" in md
