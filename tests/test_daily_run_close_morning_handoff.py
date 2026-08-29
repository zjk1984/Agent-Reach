# -*- coding: utf-8
"""Tests for close ↔ morning card handoff loop."""

from datetime import date

from agent_reach.daily_run.close_cards import CloseCardContext
from agent_reach.daily_run.close_morning_handoff import (
    build_close_handoff,
    build_morning_handoff,
    collect_tomorrow_focus_items,
    collect_watch_risk_items,
    load_close_handoff,
    render_morning_action_trace_markdown,
    render_yesterday_focus_validation_markdown,
    save_close_handoff,
    save_morning_handoff,
    validate_morning_action_lines,
    validate_tomorrow_focus_lines,
)
from agent_reach.daily_run.morning_cards import MorningCardContext, MorningSymbolRow
from agent_reach.daily_run.morning_signals import build_action_checklist_rows

PORTFOLIO_SUMMARY = {
    "end_total": 100000.0,
    "holdings": [
        {
            "code": "300308",
            "name": "中际旭创",
            "shares": 100,
            "price": 125.3,
            "weight_pct": 20.0,
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "price": 34.0,
            "weight_pct": 10.0,
        },
    ],
}

CLOSE_CTX = CloseCardContext(
    portfolio_summary=PORTFOLIO_SUMMARY,
    symbol_rows=[
        {
            "code": "300308",
            "name": "中际旭创",
            "verify": {"recommendations": ["冲高回落，关注 120 支撑"]},
        }
    ],
    verify_by_code={
        "300308": {"recommendations": ["冲高回落，关注 120 支撑"]},
    },
    technical_scenarios=[
        {
            "scenario_type": "upper_shadow",
            "code": "300308",
            "name": "中际旭创",
            "session_low": 118.0,
            "bearish": {"label": "跌破 118 减仓"},
        }
    ],
)

MORNING_PORTFOLIO = {
    "total": 100000.0,
    "holdings": [
        {
            "code": "300308",
            "name": "中际旭创",
            "shares": 100,
            "price": 123.5,
            "open": 123.5,
            "prev_close": 125.3,
            "volume_ratio": 0.8,
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "price": 34.0,
            "open": 34.2,
            "prev_close": 33.8,
            "volume_ratio": 1.2,
        },
    ],
}


def _morning_ctx(handoff: dict) -> MorningCardContext:
    return MorningCardContext(
        portfolio=MORNING_PORTFOLIO,
        close_handoff=handoff,
        symbol_rows=[
            MorningSymbolRow(
                code="300308",
                name="中际旭创",
                holding=MORNING_PORTFOLIO["holdings"][0],
                report={"verdict": "观察", "mss_final": 62.0, "stop_loss_price": 120.0},
                snapshot={},
            ),
            MorningSymbolRow(
                code="002273",
                name="水晶光电",
                holding=MORNING_PORTFOLIO["holdings"][1],
                report={"verdict": "可做", "mss_final": 58.0, "entry_price": 35.0},
                snapshot={},
            ),
        ],
    )


class TestCloseMorningHandoff:
    def test_collect_close_card_items(self):
        focus = collect_tomorrow_focus_items(CLOSE_CTX)
        risks = collect_watch_risk_items(CLOSE_CTX)
        assert any("冲高回落" in item["text"] for item in focus)
        assert any("118" in item["text"] for item in risks)

    def test_save_and_load_close_handoff(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
            tmp_path,
        )
        payload = build_close_handoff(CLOSE_CTX)
        payload["close_date"] = "2026-08-28"
        save_close_handoff(payload)
        loaded = load_close_handoff(close_day=date(2026, 8, 28))
        assert loaded is not None
        assert loaded["positions"]["300308"]["weight_pct"] == 20.0
        assert loaded["tomorrow_focus"]

    def test_morning_uses_close_position_for_action_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
            tmp_path,
        )
        handoff = {
            "close_date": "2026-08-28",
            "positions": {
                "300308": {"name": "中际旭创", "weight_pct": 20.0},
                "002273": {"name": "水晶光电", "weight_pct": 10.0},
            },
            "tomorrow_focus": [
                {"code": "300308", "name": "中际旭创", "text": "冲高回落，关注 120 支撑"},
            ],
            "watch_risks": [
                {"code": "300308", "name": "中际旭创", "text": "跌破 118 减仓", "status": "watch"},
            ],
        }
        ctx = _morning_ctx(handoff)
        rows = build_action_checklist_rows(ctx)
        by_name = {row["name"]: row for row in rows}
        assert by_name["中际旭创"]["current_weight_pct"] == 20.0
        assert "20%" in by_name["中际旭创"]["target_position"]

    def test_validate_tomorrow_focus_from_handoff(self):
        handoff = {
            "tomorrow_focus": [
                {"code": "300308", "name": "中际旭创", "text": "冲高回落，关注 120 支撑"},
            ]
        }
        ctx = _morning_ctx(handoff)
        lines = validate_tomorrow_focus_lines(ctx, limit=1)
        assert lines
        assert "昨日关注" in lines[0]
        md = render_yesterday_focus_validation_markdown(ctx)
        assert "**昨日预测验证**" in md

    def test_morning_action_trace_at_close(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.trade_calendar.today_shanghai",
            lambda: date(2026, 8, 29),
        )
        morning_payload = {
            "morning_date": "2026-08-29",
            "action_checklist": [
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "operation": "减仓",
                    "target_position": "20% → 10%",
                    "current_weight_pct": 20.0,
                    "target_weight_pct": 10.0,
                }
            ],
        }
        save_morning_handoff(morning_payload)

        close_ctx = CloseCardContext(
            portfolio_summary={
                "end_total": 100000.0,
                "holdings": [
                    {
                        "code": "300308",
                        "name": "中际旭创",
                        "shares": 80,
                        "price": 123.5,
                        "weight_pct": 9.9,
                    }
                ],
            },
            symbol_rows=[],
        )
        trace = validate_morning_action_lines(close_ctx)
        assert trace
        assert "✅" in trace[0]
        md = render_morning_action_trace_markdown(close_ctx)
        assert "**早盘操作回溯**" in md

    def test_save_morning_handoff_from_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
            tmp_path,
        )
        handoff = {"close_date": "2026-08-28", "positions": {}}
        ctx = _morning_ctx(handoff)
        rows = build_action_checklist_rows(ctx)
        payload = build_morning_handoff(ctx, rows)
        path = save_morning_handoff(payload)
        assert path.exists()
        assert payload["action_checklist"]
        assert payload["morning_predictions"]
        assert any(item["code"] == "300308" for item in payload["morning_predictions"])
