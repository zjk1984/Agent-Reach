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


def test_enrich_plan_row_signals():
    from agent_reach.daily_run.midday_content_scope import enrich_plan_row_signals

    row = enrich_plan_row_signals(
        {
            "name": "中际旭创",
            "operation": "减仓",
            "trigger": "跌破 120.00 元",
            "verify_label": "已成交",
            "filled": True,
            "changed": False,
            "change_pct": -4.87,
            "volume_ratio": 1.5,
            "data_stale": False,
            "afternoon_action": "维持早盘计划",
            "stats": {"low": 118.0, "high": 124.0, "price": 119.2},
        }
    )
    assert row["verify_status"] == "✅ 已减仓"
    assert row["verify_am_actual"] == "最低118.00"
    assert row["adjust_reason"] == "已按计划减仓"
