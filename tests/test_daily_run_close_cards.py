# -*- coding: utf-8
"""Tests for six-card close Feishu layout."""

from agent_reach.daily_run.close_cards import (
    CLOSE_CARD_ORDER,
    CloseCardContext,
    close_card_layout_enabled,
    collect_harness_evolution_rows,
    collect_holdings_ledger_rows,
    render_close_card_sections,
    render_close_summary_markdown,
    render_forecast_verify_markdown,
    render_harness_evolution_markdown,
    render_holdings_detail_markdown,
    render_holdings_ledger_markdown,
    render_tomorrow_focus_markdown,
)


PORTFOLIO_SUMMARY = {
    "daily_pnl": 1250.0,
    "daily_pnl_pct": 1.2,
    "cash_ratio": 0.42,
    "cash": 42000.0,
    "end_total": 100000.0,
    "stock_mv": 58000.0,
    "total_unrealized": -5000.0,
    "watchlist_count": 2,
    "reason_lines": ["验证结论 **观察**，观察池 5 只"],
    "holdings": [
        {
            "code": "688008",
            "name": "澜起科技",
            "shares": 100,
            "cost": 255.87,
            "price": 255.0,
            "market_value": 25500.0,
            "weight_pct": 25.5,
            "day_pnl": 150.0,
            "unrealized_pnl": -87.0,
            "change_pct": 1.5,
            "days_held": 31,
            "sector": "半导体",
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "cost": 34.5,
            "price": 34.0,
            "market_value": 10200.0,
            "weight_pct": 10.2,
            "day_pnl": -80.0,
            "unrealized_pnl": -150.0,
            "change_pct": -0.8,
            "acquired_date": "2026-08-01",
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
        assert sections[1].title.startswith("📒 持仓台账")
        assert sections[3].title.startswith("🔮 预测验证")
        assert sections[5].title.startswith("🧬 Harness 自进化")

    def test_holdings_ledger_table(self):
        rows = collect_holdings_ledger_rows(PORTFOLIO_SUMMARY)
        assert len(rows) == 2
        assert rows[0]["code"] == "688008"
        md = render_holdings_ledger_markdown(
            CloseCardContext(portfolio_summary=PORTFOLIO_SUMMARY, symbol_rows=SYMBOL_ROWS)
        )
        assert "| 澜起科技 | 688008 | 100 |" in md
        assert "¥255.87" in md
        assert "+¥150" in md
        assert "天" in md
        assert "2026-08-01" in md or "水晶光电" in md
        assert "持仓市值" in md
        assert "观察池" in md
        assert "兆易创新" not in md

    def test_holdings_ledger_excludes_watchlist_only(self):
        pf = {
            **PORTFOLIO_SUMMARY,
            "holdings": list(PORTFOLIO_SUMMARY["holdings"])
            + [{"code": "603986", "name": "兆易创新", "shares": 0, "price": 380.0}],
        }
        assert len(collect_holdings_ledger_rows(pf)) == 2

    def test_harness_evolution_table(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            settings={
                "harness_runtime": {
                    "threshold_overlay": {
                        "macro_veto": {"base": 40.0, "effective": 30.0},
                        "min_cash_ratio": {"base": 0.0, "effective": 0.5},
                    },
                    "position_overlay": {
                        "deploy_ratio": {"base": 1.0, "effective": 0.15},
                    },
                    "trade_signals": {"defensive_trim": True},
                }
            },
            harness_result={
                "layer_a": {"refinement_id": "refine_0001", "changes": 2, "proposal_summary": "收盘 Layer A 调参"},
                "layer_b": {"refinement_id": "refine_0002", "changes": 1, "proposal_summary": "macro_veto 下调"},
            },
        )
        rows = collect_harness_evolution_rows(ctx)
        assert len(rows) >= 3
        macro = next(r for r in rows if r["param"] == "宏观否决线")
        assert macro["baseline"] == "40"
        assert macro["evolved"] == "30"
        md = render_harness_evolution_markdown(ctx)
        assert "| 参数 | 原有 | 自进化 | 原因 |" in md
        assert "宏观否决线" in md
        assert "deploy_ratio" in md

    def test_summary_contains_pnl_and_table(self):
        ctx = CloseCardContext(
            portfolio_summary=PORTFOLIO_SUMMARY,
            symbol_rows=SYMBOL_ROWS,
            market_review={"indices": {"000300": {"name": "沪深300", "change_pct": 0.4}}},
        )
        md = render_close_summary_markdown(ctx)
        assert "当日盈亏" in md
        assert "+¥1,250（+1.20%）" in md
        assert "组合 **+1.20%** vs 沪深300 **+0.40%**（超额 **+0.80%**）" in md
        assert "澜起科技" in md
        assert "风控" in md

    def test_summary_pnl_pct_not_double_scaled(self):
        ctx = CloseCardContext(
            portfolio_summary={
                "daily_pnl": -457.0,
                "daily_pnl_pct": -0.43,
            },
            market_review={"indices": {"000300": {"name": "沪深300", "change_pct": 0.35}}},
        )
        md = render_close_summary_markdown(ctx)
        assert "¥-457（-0.43%）" in md
        assert "组合 **-0.43%** vs 沪深300 **+0.35%**（超额 **-0.78%**）" in md
        assert "-43.00%" not in md
        assert "+35.00%" not in md

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
