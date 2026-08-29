# -*- coding: utf-8
"""Tests for midday ↔ morning ↔ close handoff data loop."""

from datetime import date

from agent_reach.daily_run.close_cards import CloseCardContext
from agent_reach.daily_run.midday_cards import MiddayCardContext, build_midday_plan_rows
from agent_reach.daily_run.midday_content_scope import enrich_plan_row_signals
from agent_reach.daily_run.midday_handoff import (
    build_midday_handoff,
    load_midday_handoff,
    render_midday_close_loop_markdown,
    save_midday_handoff,
    validate_midday_adjustments,
    validate_midday_anomaly_signals,
)

MORNING_HANDOFF = {
    "morning_date": "2026-08-29",
    "action_checklist": [
        {
            "code": "300308",
            "name": "中际旭创",
            "operation": "减仓",
            "trigger": "跌破 120.00 元",
            "target_position": "20% → 10%",
            "current_weight_pct": 20.0,
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
    ],
    "positions_at_morning": {
        "300308": {"name": "中际旭创", "weight_pct": 20.0},
        "000725": {"name": "京东方", "weight_pct": 8.0},
    },
    "morning_predictions": [
        {
            "code": "300308",
            "name": "中际旭创",
            "prediction": "冲高回落，关注 120 支撑",
            "source": "report",
        }
    ],
}

ENRICHED = {
    "portfolio": {
        "total": 100000.0,
        "holdings": [
            {
                "code": "300308",
                "name": "中际旭创",
                "shares": 80,
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
                "shares": 200,
                "open": 4.5,
                "price": 4.52,
                "prev_close": 4.48,
                "volume_ratio": 0.9,
            },
        ],
    },
}


def _midday_ctx(**overrides) -> MiddayCardContext:
    plan_rows = [
        enrich_plan_row_signals(row)
        for row in build_midday_plan_rows(
            morning_handoff=MORNING_HANDOFF,
            enriched=ENRICHED,
            state={"scans": [], "trades": []},
        )
    ]
    defaults = {
        "plan_rows": plan_rows,
        "holdings_am_rows": [
            {
                "code": "300308",
                "name": "中际旭创",
                "am_close": 118.5,
                "change_pct": -2.87,
                "volume_ratio": 1.2,
            },
            {
                "code": "000725",
                "name": "京东方",
                "am_close": 4.52,
                "change_pct": 0.89,
                "volume_ratio": 0.9,
            },
        ],
        "prediction_verify_items": [
            {
                "code": "300308",
                "name": "中际旭创",
                "prediction": "冲高回落，关注 120 支撑",
                "am_change_pct": -2.87,
                "hit": True,
            }
        ],
        "anomaly_signal_items": [
            {
                "code": "300308",
                "name": "中际旭创",
                "severity": "red",
                "text": "上午放量下跌 -2.87%",
                "change_pct": -2.87,
                "volume_ratio": 1.2,
            }
        ],
        "morning_handoff": MORNING_HANDOFF,
    }
    defaults.update(overrides)
    return MiddayCardContext(**defaults)


class TestMiddayHandoff:
    def test_build_and_save_midday_handoff(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_reach.daily_run.midday_handoff._HANDOFF_DIR", tmp_path)
        ctx = _midday_ctx()
        payload = build_midday_handoff(ctx, morning_handoff=MORNING_HANDOFF, portfolio=ENRICHED["portfolio"])
        path = save_midday_handoff(payload)

        assert path.exists()
        loaded = load_midday_handoff(midday_day=date(2026, 8, 29))
        assert loaded is not None
        assert loaded["morning_plan_verify"]
        assert loaded["afternoon_adjustments"]
        assert loaded["positions_at_morning"]["300308"]["weight_pct"] == 20.0
        assert loaded["positions_at_am_close"]["300308"]["change_pct"] == -2.87
        assert loaded["position_changes"]
        assert loaded["morning_predictions"]

    def test_validate_midday_adjustments_pm_sell(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_reach.daily_run.midday_handoff._HANDOFF_DIR", tmp_path)
        ctx = _midday_ctx()
        payload = build_midday_handoff(ctx, morning_handoff=MORNING_HANDOFF)
        for adj in payload["afternoon_adjustments"]:
            if adj.get("code") == "300308":
                adj["adjusted_plan"] = "减仓"
                adj["changed"] = True
        save_midday_handoff(payload)

        close_ctx = CloseCardContext(
            portfolio_summary={
                "holdings": [
                    {"code": "300308", "name": "中际旭创", "weight_pct": 9.5},
                ]
            },
            symbol_rows=[],
        )
        state = {
            "trades": [
                {
                    "portfolio_applied": True,
                    "as_of": "2026-08-29T13:30:00+08:00",
                    "actions": [{"side": "sell", "code": "300308", "shares": 20, "price": 118.0}],
                }
            ]
        }
        lines = validate_midday_adjustments(close_ctx, state=state)
        assert lines
        assert any("✅" in line and "中际旭创" in line for line in lines)

    def test_validate_midday_anomaly_fermentation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_reach.daily_run.midday_handoff._HANDOFF_DIR", tmp_path)
        ctx = _midday_ctx()
        save_midday_handoff(build_midday_handoff(ctx, morning_handoff=MORNING_HANDOFF))

        close_ctx = CloseCardContext(
            portfolio_summary={"holdings": []},
            symbol_rows=[
                {
                    "code": "300308",
                    "name": "中际旭创",
                    "change_pct": -5.2,
                    "verify": {"price_delta_pct": -5.2},
                }
            ],
            verify_by_code={"300308": {"price_delta_pct": -5.2}},
        )
        lines = validate_midday_anomaly_signals(close_ctx)
        assert lines
        assert any("发酵" in line or "缓解" in line or "震荡" in line for line in lines)

    def test_render_midday_close_loop_markdown(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_reach.daily_run.midday_handoff._HANDOFF_DIR", tmp_path)
        ctx = _midday_ctx()
        payload = build_midday_handoff(ctx, morning_handoff=MORNING_HANDOFF)
        for adj in payload["afternoon_adjustments"]:
            adj["adjusted_plan"] = "维持"
            adj["changed"] = False
        save_midday_handoff(payload)

        close_ctx = CloseCardContext(
            portfolio_summary={
                "holdings": [
                    {"code": "300308", "name": "中际旭创", "weight_pct": 20.0},
                    {"code": "000725", "name": "京东方", "weight_pct": 8.0},
                ]
            },
            symbol_rows=[
                {"code": "300308", "name": "中际旭创", "change_pct": -3.5},
            ],
        )
        md = render_midday_close_loop_markdown(close_ctx, state={"trades": []})
        assert "**午盘→收盘回溯**" in md
        assert "下午操作验证" in md
