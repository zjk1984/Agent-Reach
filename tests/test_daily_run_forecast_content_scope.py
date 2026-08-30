# -*- coding: utf-8
"""Tests for Sunday forecast content de-duplication."""

from agent_reach.daily_run.forecast_content_scope import (
    apply_holdings_char_budget,
    build_forecast_content_scope,
    build_macro_brief_with_impact,
    extract_buy_candidates,
    filter_sectors_to_holdings,
    format_compact_symbol_line,
    holding_sector_names,
)


def test_holding_sector_filter():
    sectors = [
        {"name": "半导体", "text": "半导体预测"},
        {"name": "消费", "text": "消费预测"},
    ]
    pf = {"holdings": [{"code": "603986", "name": "兆易创新"}]}
    settings = {"watchlist": {"sector_map": {"603986": "存储"}}}
    out = filter_sectors_to_holdings(sectors, portfolio=pf, settings=settings)
    assert out == []


def test_macro_brief_max_100_chars():
    brief = build_macro_brief_with_impact(
        snapshot={"macro_summary": "美联储鹰派表态", "mss_final": 52},
        portfolio={"holdings": [{"code": "300308", "name": "中际旭创"}]},
        settings={"watchlist": {"sector_map": {"300308": "光通信"}}},
    )
    assert brief.get("text")
    assert len(brief["text"]) <= 100
    assert "→" in brief["text"]


def test_compact_symbol_with_core_factors():
    line = format_compact_symbol_line(
        {"name": "中际旭创", "price_low": 110, "price_high": 125, "confidence_pct": 75},
        core_factors=["①订单回暖", "②接近前高125元压力位"],
    )
    assert "核心因素" in line
    assert "110-125" in line


def test_holdings_char_budget():
    lines = [
        "A" * 120,
        "B" * 120,
        "C" * 120,
    ]
    out = apply_holdings_char_budget(lines, budget=300)
    assert sum(len(s) for s in out) <= 300


def test_extract_buy_candidates():
    outlook = {
        "operation_plan": [
            {"code": "603986", "name": "兆易创新", "action": "新建仓", "trigger": "突破200元", "target_weight": "15%"},
        ]
    }
    rows = extract_buy_candidates(outlook, held_codes=set())
    assert len(rows) == 1
    assert rows[0]["label"] == "新建仓候选"


def test_build_forecast_content_scope():
    structured = {
        "market": {"change_pct_low": 0.5, "change_pct_high": 1.5, "index_name": "沪深300"},
        "sectors": [{"name": "半导体", "text": "半导体超额 +1~+3%"}],
        "symbols": [
            {
                "code": "300308",
                "name": "中际旭创",
                "price_low": 110,
                "price_high": 125,
                "confidence_pct": 70,
            }
        ],
    }
    scope = build_forecast_content_scope(
        structured=structured,
        forecast={"week_start": "2026-08-31", "symbols": {}, "kronos_paths": {}},
        portfolio={"holdings": [{"code": "300308", "name": "中际旭创"}]},
        settings={"watchlist": {"sector_map": {"300308": "光通信"}}},
    )
    assert scope.get("weekly_recap")
    assert scope.get("symbols_compact")
    assert len(scope["symbols_compact"]) >= 1
