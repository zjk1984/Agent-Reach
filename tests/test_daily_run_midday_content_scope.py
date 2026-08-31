# -*- coding: utf-8
"""Tests for scoped midday card content."""

import pytest

from agent_reach.daily_run.midday_content_scope import (
    MIDDAY_PLAN_UNCHANGED,
    MIDDAY_REBALANCE_REMINDER,
    build_am_market_key_points,
    build_holdings_am_brief_rows,
    build_lunch_news_lines,
    build_macro_holdings_impact_line,
    build_morning_reference_line,
    build_rebalance_window_reminder,
    build_t0_opportunity_lines,
    compact_afternoon_display,
    compute_halfday_pnl,
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


def test_compute_halfday_pnl_from_am_close():
    result = compute_halfday_pnl(
        portfolio={
            "cash": 20000.0,
            "holdings": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "shares": 100,
                    "prev_close": 122.0,
                    "price": 118.5,
                }
            ],
        },
        holdings_am_rows=[
            {
                "code": "300308",
                "name": "中际旭创",
                "prev_close": 122.0,
                "am_close": 118.5,
                "change_pct": -2.87,
            }
        ],
    )
    assert result["halfday_pnl"] == -350.0
    assert result["halfday_pnl_pct"] is not None
    assert "上午盈亏" in result["line"]


def test_build_rebalance_window_reminder():
    assert build_rebalance_window_reminder() == MIDDAY_REBALANCE_REMINDER
    assert "14:00" in MIDDAY_REBALANCE_REMINDER


def test_build_lunch_news_lines_from_intel_and_hot_topics():
    lines = build_lunch_news_lines(
        {
            "watchlist_intel": {
                "300308": {
                    "announcements": [{"title": "关于签订重大合同的公告"}],
                }
            },
            "macro_signals": {
                "hot_topics_matched": [{"title": "AI算力板块政策利好"}],
            },
        },
        {
            "holdings": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "shares": 100,
                    "sector": "AI算力",
                }
            ]
        },
    )
    assert lines
    assert len(lines) <= 3
    assert any("中际旭创" in line or "AI算力" in line for line in lines)


def test_build_t0_opportunity_lines_for_volatile_holding():
    lines = build_t0_opportunity_lines(
        [
            {
                "name": "中际旭创",
                "change_pct": -4.2,
                "prev_close": 122.0,
                "am_close": 116.9,
                "am_high": 121.0,
                "am_low": 116.5,
            }
        ]
    )
    assert lines
    assert "T+0" in lines[0]
    assert "121.00" in lines[0]
    assert "116.50" in lines[0]


def test_build_t0_opportunity_lines_use_per_holding_prices():
    """Primary-symbol prev_close / scan prices must not bleed into other holdings."""
    lines = build_t0_opportunity_lines(
        [
            {
                "code": "000725",
                "name": "京东方",
                "change_pct": 3.2,
                "prev_close": 4.45,
                "am_close": 4.59,
                "am_high": 4.62,
                "am_low": 4.38,
            },
            {
                "code": "002583",
                "name": "海能达",
                "change_pct": 5.8,
                "prev_close": 12.0,
                "am_close": 12.70,
                "am_high": 12.95,
                "am_low": 12.35,
            },
        ],
        limit=2,
    )
    assert len(lines) == 2
    assert lines[0] != lines[1]
    assert "京东方" in lines[1] or "京东方" in lines[0]
    assert "海能达" in lines[1] or "海能达" in lines[0]
    boe_line = next(line for line in lines if "京东方" in line)
    htd_line = next(line for line in lines if "海能达" in line)
    assert "4.59" in boe_line
    assert "12.70" in htd_line


def test_build_holdings_am_brief_rows_no_primary_snapshot_bleed(monkeypatch):
    from agent_reach.daily_run.intraday import IntradayState

    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.load_state",
        lambda *_a, **_k: IntradayState(date="2026-08-31"),
    )
    rows = build_holdings_am_brief_rows(
        portfolio={
            "holdings": [
                {
                    "code": "000725",
                    "name": "京东方",
                    "price": 4.59,
                    "open": 4.40,
                    "prev_close": 4.45,
                },
                {
                    "code": "002583",
                    "name": "海能达",
                    "price": 12.70,
                    "open": 12.10,
                    "prev_close": 12.0,
                },
            ]
        },
        plan_rows=[],
        enriched={
            "code": "000725",
            "name": "京东方",
            "prev_close": 4.45,
            "price": 4.59,
        },
        am_scans=[
            {"scan_id": "S7", "code": "000725", "price": 4.62},
            {"scan_id": "S6", "code": "000725", "price": 4.38},
        ],
        state={"scans": [{"scan_id": "S7", "code": "000725", "price": 4.62}]},
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["京东方"]["prev_close"] == pytest.approx(4.45)
    assert by_name["海能达"]["prev_close"] == pytest.approx(12.0)
    assert by_name["京东方"]["am_high"] == pytest.approx(4.62)
    assert by_name["海能达"]["am_high"] == pytest.approx(12.70)
    assert by_name["海能达"]["am_low"] == pytest.approx(12.10)
