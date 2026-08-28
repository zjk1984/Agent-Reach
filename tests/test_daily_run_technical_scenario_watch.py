# -*- coding: utf-8
"""Tests for upper-shadow technical scenario watch."""

from datetime import date

import pytest

from agent_reach.daily_run.technical_scenario_watch import (
    evaluate_scenario,
    format_technical_scenario_markdown,
    load_scenarios,
    maybe_register_upper_shadow_from_session,
    register_upper_shadow_scenario,
    save_scenarios,
    technical_scenario_harness_evidence,
)


@pytest.fixture
def scenario_path(tmp_path):
    return tmp_path / "technical_scenarios.json"


def test_register_upper_shadow_scenario(scenario_path):
    row = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["session_low"] == 856.63
    assert row["eval_from"] == "2026-08-31"
    saved = load_scenarios(scenario_path)
    assert len(saved) == 1
    assert saved[0]["scenario_type"] == "upper_shadow"


def test_evaluate_bearish_break_below_low(scenario_path):
    scenario = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=855.0, change_pct=-1.2)
    assert result["status"] == "bearish_confirmed"
    assert "见顶" in result["headline"]


def test_evaluate_bullish_reclaim_high(scenario_path):
    scenario = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=916.0, change_pct=6.5, open_price=870.0)
    assert result["status"] == "bullish_washout"
    assert "洗盘" in result["headline"]


def test_harness_writes_sell_late_on_bearish_confirm(scenario_path, monkeypatch):
    register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 31),
    )
    from agent_reach.daily_run.technical_scenario_watch import evaluate_active_scenarios

    evals = evaluate_active_scenarios(
        {"code": "300308", "price": 850.0, "change_pct": -2.0},
        as_of=date(2026, 8, 31),
        path=scenario_path,
    )
    lines = technical_scenario_harness_evidence(evals, path=scenario_path)
    assert any("卖晚了" in item for item in lines["memory"])
    assert load_scenarios(scenario_path)[0]["status"] == "bearish_confirmed"


def test_maybe_register_from_session(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    row = maybe_register_upper_shadow_from_session(
        code="300308",
        name="中际旭创",
        snapshot={
            "code": "300308",
            "price": 858.35,
            "change_pct": 5.74,
            "day_high": 915.88,
            "day_low": 856.63,
        },
        session_scans=[{"code": "300308", "price": 896.74}],
        path=scenario_path,
    )
    assert row is not None
    assert load_scenarios(scenario_path)[0]["session_high"] == 915.88


def test_format_markdown():
    md = format_technical_scenario_markdown(
        [{"headline": "中际旭创 长上影后续：跌破 856.63 确认短期见顶"}]
    )
    assert "技术情景跟踪" in md
    assert "856.63" in md
