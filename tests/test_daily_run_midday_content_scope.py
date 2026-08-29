# -*- coding: utf-8
"""Tests for scoped midday card content."""

from agent_reach.daily_run.midday_content_scope import (
    MIDDAY_PLAN_UNCHANGED,
    build_am_market_key_points,
    build_macro_holdings_impact_line,
    build_morning_reference_line,
    compact_afternoon_display,
)


def test_build_am_market_key_points_from_signals():
    points = build_am_market_key_points(
        {
            "macro_signals": {"index_change_pct": 0.3, "northbound_flow_yi": 12.0},
            "indices": {
                "sz399006": {"change_pct": -0.5},
                "sh000001": {"amount": 4e11},
                "sz399001": {"amount": 3.5e11},
            },
            "portfolio": {
                "holdings": [
                    {"code": "300308", "name": "中际旭创", "sector": "AI算力", "price": 120, "prev_close": 118}
                ]
            },
        }
    )
    assert any("上证" in p for p in points)
    assert any("创业板" in p for p in points)
    assert 3 <= len(points) <= 5


def test_build_macro_holdings_impact_line():
    line = build_macro_holdings_impact_line(
        {"macro_signals": {"index_change_pct": -1.2}},
        portfolio={"holdings": [{"code": "300308", "sector": "半导体"}]},
    )
    assert "对持仓影响" in line


def test_build_morning_reference_line():
    line = build_morning_reference_line(
        {
            "action_checklist": [
                {"name": "中际旭创", "operation": "减仓", "trigger": "跌破 120 元"},
            ]
        }
    )
    assert line.startswith("早盘提到")


def test_compact_afternoon_display_unchanged():
    assert compact_afternoon_display({"changed": False}) == MIDDAY_PLAN_UNCHANGED
