# -*- coding: utf-8
"""Tests for structured midday cards (plan verify + afternoon adjust)."""

from datetime import date
from unittest.mock import patch

from agent_reach.daily_run.midday_cards import (
    MIDDAY_CARD_ORDER,
    build_midday_card_context,
    build_midday_plan_rows,
    midday_card_layout_enabled,
    render_afternoon_risk_markdown,
    render_midday_card_sections,
    render_plan_verify_markdown,
    render_session_brief_markdown,
)


def test_midday_card_layout_enabled_by_default():
    assert midday_card_layout_enabled({}) is True
    assert midday_card_layout_enabled({"report": {"midday_card_layout": "legacy"}}) is False


def test_plan_verify_table_columns():
    rows = build_midday_plan_rows(
        morning_handoff={
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "减仓",
                    "trigger": "跌破 120.00 元",
                    "target_position": "10% → 10%",
                    "current_weight_pct": 12.0,
                    "target_weight_pct": 10.0,
                },
                {
                    "code": "000725",
                    "name": "京东方",
                    "operation": "观望",
                    "trigger": "—",
                    "target_position": "维持 8%",
                    "current_weight_pct": 8.0,
                    "target_weight_pct": 8.0,
                },
            ]
        },
        enriched={
            "portfolio": {
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 100,
                        "open": 119.0,
                        "price": 118.5,
                        "low": 118.0,
                        "high": 121.0,
                        "prev_close": 122.0,
                        "volume_ratio": 1.2,
                    },
                    {
                        "code": "000725",
                        "name": "京东方",
                        "shares": 1000,
                        "open": 4.2,
                        "price": 4.5,
                        "low": 4.1,
                        "high": 4.5,
                        "prev_close": 4.45,
                        "volume_ratio": 0.9,
                    },
                ]
            }
        },
        state={
            "scans": [
                {"scan_id": "S7", "mss_final": 52.0, "verdict": "观察", "price": 118.5},
            ]
        },
    )
    assert len(rows) == 2
    assert rows[0].get("verify_status")
    assert rows[0].get("trigger_cond")
    assert "截至 11:30 收盘" in rows[0]["position_change"]
    md = render_plan_verify_markdown(
        type(
            "Ctx",
            (),
            {
                "plan_rows": rows,
                "plan_unchanged": not any(r.get("changed") for r in rows),
                "audit_banner": "",
                "data_as_of": "截至 11:30 收盘",
                "data_quality_notes": [],
                "morning_diverged": False,
                "morning_diverged_note": "",
                "timeline_nodes": [{"time": "13:00", "event": "下午开盘", "impact": "—"}],
            },
        )()
    )
    assert "| 股票 | 早盘计划 | 触发条件 | 上午实际 | 状态 |" in md
    assert "| 股票 | 原计划 | 调整后 | 调整原因 | 触发条件 |" in md
    assert "| 时间 | 事件 | 影响 |" in md
    assert "中际旭创" in md
    assert "截至 11:30 收盘" in md


def test_plan_unchanged_shows_maintain_in_adjustment_table():
    rows = [
        {
            "name": "水晶光电",
            "original_plan": "加仓",
            "adjusted_plan": "观望",
            "adjust_reason": "上午未突破，量能不足",
            "afternoon_trigger": "等待明确信号",
            "verify_operation": "加仓",
            "trigger_cond": "突破35",
            "verify_am_actual": "最高34.8",
            "verify_status": "❌ 未触发",
            "changed": True,
        }
    ]
    ctx = type(
        "Ctx",
        (),
        {
            "plan_rows": rows,
            "plan_unchanged": True,
            "audit_banner": "",
            "data_as_of": "截至 11:30 收盘",
            "data_quality_notes": [],
            "morning_diverged": False,
            "morning_diverged_note": "",
            "timeline_nodes": [],
        },
    )()
    md = render_plan_verify_markdown(ctx)
    assert "下午操作调整清单" in md
    assert "观望" in md


@patch("agent_reach.daily_run.midday.apply_midday_macro_refresh", side_effect=lambda s, **_: s)
@patch("agent_reach.daily_run.intraday.record_scan_from_evaluation")
@patch("agent_reach.daily_run.pipeline.evaluate_snapshot")
def test_run_midday_uses_card_layout(mock_eval, mock_record, _mock_macro):
    from agent_reach.daily_run.intraday import IntradayState
    from agent_reach.daily_run.midday import run_midday

    state = IntradayState(
        date="2026-08-27",
        scans=[{"scan_id": "S7", "mss_final": 55.0, "verdict": "观察", "price": 255.0}],
    )
    handoff = {
        "morning_date": "2026-08-27",
        "action_checklist": [
            {
                "code": "688008",
                "name": "澜起科技",
                "operation": "持有",
                "trigger": "—",
                "target_position": "维持 20%",
                "current_weight_pct": 20.0,
                "target_weight_pct": 20.0,
            }
        ],
    }
    with patch("agent_reach.daily_run.intraday.load_state", return_value=state), patch(
        "agent_reach.daily_run.macro_collector.fetch_intraday_xueqiu_cross_alerts",
        return_value={},
    ), patch(
        "agent_reach.daily_run.auditor.run_data_audit",
        return_value=type("A", (), {"passed": True, "warnings": [], "issues": []})(),
    ), patch(
        "agent_reach.daily_run.close_morning_handoff.load_morning_handoff",
        return_value=handoff,
    ):
        result = run_midday(
            {
                "code": "688008",
                "name": "澜起科技",
                "price": 255.0,
                "prev_close": 250.0,
                "portfolio": {
                    "holdings": [
                        {"code": "688008", "name": "澜起科技", "shares": 100, "price": 255.0, "open": 252.0}
                    ]
                },
            },
            settings={"midday": {"enabled": True, "record_scan": False}},
            push=False,
        )
    assert result.get("midday_card_layout") is True
    assert "render_cards" in result["steps"]
    assert "午休宏观刷新" not in result["markdown"]
    assert "早盘计划验证汇总" in result["markdown"] or "下午操作调整清单" in result["markdown"]


def test_card_section_count():
    ctx = build_midday_card_context(
        {
            "scan": {"scan_id": "12:30", "mss_final": 55, "verdict": "观察", "record_scan_skipped": True},
            "state": {"scans": [{"scan_id": "S7", "mss_final": 55, "verdict": "观察"}]},
            "enriched": {
                "code": "688008",
                "name": "澜起科技",
                "portfolio": {"holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "price": 255}]},
            },
            "lookback_mss": 54.0,
            "trend": "flat",
            "anchor_trend": "flat",
        },
        settings={},
    )
    sections = render_midday_card_sections(ctx)
    assert len(MIDDAY_CARD_ORDER) == 3
    assert 2 <= len(sections) <= 4
    labels = [s.title for s in sections]
    assert any("早盘验证" in t for t in labels)
    assert any("持仓上午" in t for t in labels)


def test_verify_from_actual_trade_fill():
    rows = build_midday_plan_rows(
        morning_handoff={
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "减仓",
                    "trigger": "跌破 120.00 元",
                    "target_position": "12% → 10%",
                    "current_weight_pct": 12.0,
                    "target_weight_pct": 10.0,
                }
            ]
        },
        enriched={
            "portfolio": {
                "cash": 88000,
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 100,
                        "price": 119.5,
                        "open": 119.0,
                        "low": 118.0,
                        "high": 121.0,
                        "prev_close": 122.0,
                        "volume_ratio": 1.1,
                    }
                ],
            }
        },
        state={
            "trades": [
                {
                    "as_of": "2026-08-29T03:15:00+00:00",
                    "portfolio_applied": True,
                    "portfolio_actions": [
                        {
                            "side": "sell",
                            "code": "300308",
                            "shares": 20,
                            "price": 119.5,
                        }
                    ],
                }
            ]
        },
        day=date(2026, 8, 29),
    )
    assert len(rows) == 1
    assert "已成交" in rows[0]["verify"]
    assert "119.5" in rows[0]["verify"]
    assert rows[0]["verify_source"] == "成交记录"


def test_stale_data_shows_updating():
    rows = build_midday_plan_rows(
        morning_handoff={
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "持有",
                    "trigger": "—",
                    "current_weight_pct": 12.0,
                    "target_weight_pct": 12.0,
                }
            ]
        },
        enriched={
            "portfolio": {
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 100,
                        "price": 118.5,
                        "prev_close": 122.0,
                    }
                ]
            }
        },
        state={"scans": []},
    )
    assert rows[0]["am_actual"] == "⚠️ 数据更新中"
    assert "待行情更新" in rows[0]["afternoon_action"]

def test_am_triggered_afternoon_follow_up():
    rows = build_midday_plan_rows(
        morning_handoff={
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "减仓",
                    "trigger": "跌破 120.00 元",
                    "current_weight_pct": 12.0,
                    "target_weight_pct": 10.0,
                }
            ]
        },
        enriched={
            "portfolio": {
                "cash": 88000,
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 100,
                        "price": 118.5,
                        "open": 119.0,
                        "low": 118.0,
                        "high": 121.0,
                        "prev_close": 122.0,
                        "volume_ratio": 1.0,
                    }
                ],
            }
        },
        state={"scans": []},
    )
    assert rows[0]["am_triggered"] is True
    assert rows[0]["changed"] is True
    assert (
        "已触发" in rows[0]["afternoon_action"]
        or "触及" in rows[0]["verify_status"]
        or "未成交" in rows[0]["verify_status"]
    )


def test_position_change_morning_to_am_close():
    rows = build_midday_plan_rows(
        morning_handoff={
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "减仓",
                    "trigger": "—",
                    "current_weight_pct": 12.0,
                    "target_weight_pct": 10.0,
                }
            ]
        },
        enriched={
            "portfolio": {
                "cash": 90000,
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 80,
                        "price": 100.0,
                        "open": 100.0,
                        "low": 99.0,
                        "high": 101.0,
                        "prev_close": 100.0,
                        "volume_ratio": 1.0,
                    }
                ],
            }
        },
        state={"scans": []},
    )
    assert "早盘 12% → 上午收盘" in rows[0]["position_change"]


def test_morning_diverged_headline():
    with patch(
        "agent_reach.daily_run.close_morning_handoff.load_morning_handoff",
        return_value={
            "action_checklist": [
                {
                    "code": "000725",
                    "name": "京东方",
                    "operation": "观望",
                    "trigger": "—",
                    "current_weight_pct": 8.0,
                    "target_weight_pct": 8.0,
                }
            ]
        },
    ):
        ctx = build_midday_card_context(
            {
                "scan": {"scan_id": "12:30", "mss_final": 55, "verdict": "观察"},
                "state": {"scans": [{"scan_id": "S7", "mss_final": 55, "verdict": "观察"}]},
                "enriched": {
                    "code": "000725",
                    "name": "京东方",
                    "portfolio": {
                        "cash": 92000,
                        "holdings": [
                            {
                                "code": "000725",
                                "name": "京东方",
                                "shares": 1000,
                                "price": 4.5,
                                "open": 4.2,
                                "low": 4.1,
                                "high": 4.5,
                                "prev_close": 4.45,
                                "volume_ratio": 0.9,
                            }
                        ],
                    },
                },
                "lookback_mss": 54.0,
                "trend": "flat",
                "anchor_trend": "flat",
            },
            settings={},
        )
    md = render_plan_verify_markdown(ctx)
    assert "上午实际走势超预期" in md or "⚠️ 超预期" in md


def test_midday_am_features_render_in_cards():
    ctx = build_midday_card_context(
        {
            "scan": {"scan_id": "12:30", "mss_final": 55, "verdict": "观察"},
            "state": {"scans": [{"scan_id": "S7", "mss_final": 55, "verdict": "观察"}]},
            "enriched": {
                "portfolio": {
                    "cash": 20000.0,
                    "holdings": [
                        {
                            "code": "300308",
                            "name": "中际旭创",
                            "shares": 100,
                            "price": 118.5,
                            "open": 119.0,
                            "low": 116.5,
                            "high": 121.0,
                            "prev_close": 122.0,
                            "volume_ratio": 1.5,
                        }
                    ],
                },
                "watchlist_intel": {
                    "300308": {"announcements": [{"title": "签订重大合同公告"}]},
                },
            },
            "lookback_mss": 54.0,
            "trend": "flat",
            "anchor_trend": "flat",
        },
        settings={},
    )
    plan_md = render_plan_verify_markdown(ctx)
    brief_md = render_session_brief_markdown(ctx)
    risk_md = render_afternoon_risk_markdown(ctx)

    assert "调仓窗口提醒" in plan_md
    assert "14:00" in plan_md
    assert "上午盈亏" in brief_md
    assert "午间消息面" in brief_md or "中际旭创" in brief_md
    assert "T+0" in risk_md
