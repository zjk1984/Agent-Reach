# -*- coding: utf-8
"""Tests for decision trace (jev-trader pattern)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_reach.daily_run.decision_model import MockDecisionModel, create_decision_model
from agent_reach.daily_run.decision_trace import (
    append_decision_event,
    build_decision_state,
    build_event_from_trade_eval,
    build_late_scan_event,
    daily_trace_totals,
    decision_trace_enabled,
    render_decision_trace_markdown,
    trace_jsonl_path,
)
from agent_reach.daily_run.intraday import TradeDecision


@pytest.fixture
def trace_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REACH_DECISION_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test")
    return tmp_path


def test_decision_trace_enabled_default():
    assert decision_trace_enabled({"decision_trace": {"enabled": True}}) is True
    assert decision_trace_enabled({"decision_trace": {"enabled": False}}) is False


def test_build_late_scan_event(trace_env):
    evt = build_late_scan_event(
        job="intraday",
        scan_id="S10",
        code="688008",
        name="澜起科技",
        reason="lock busy",
    )
    path = append_decision_event(evt, settings={"decision_trace": {"enabled": True}})
    assert path is not None
    assert path.is_file()
    md = render_decision_trace_markdown(evt)
    assert "late_scan" in md
    assert "688008" in md


def test_build_event_guard_capped(trace_env):
    decision = TradeDecision(
        action="buy",
        trade_id="T1",
        lookback_mss=51.7,
        lookback_detail=[],
        trend="rising",
        reasoning="688008 可部署买入预算 ¥9,859 不足一手（200 股 @ ¥210.70 ≈ ¥42,203）",
        blocked=True,
        block_kind="buy_budget",
    )
    apply = MagicMock()
    apply.to_dict.return_value = {
        "applied": False,
        "message": decision.reasoning,
        "actions": [],
    }
    evt = build_event_from_trade_eval(
        job="intraday",
        scan_id="S11",
        report={"code": "688008", "name": "澜起科技", "mss_final": 51.7, "verdict": "可做"},
        snapshot={"code": "688008", "price": 210.7, "portfolio": {"holdings": [], "cash": 50000, "total": 100000}},
        decision=decision,
        apply_result=apply,
        lookback_mss=51.7,
        trend="rising",
        scans=[{"scan_id": "S11", "mss_final": 51.7, "price": 210.7}],
    )
    append_decision_event(evt)
    md = render_decision_trace_markdown(evt)
    assert "guard_capped" in md
    assert "可做" in md or "buy" in md


def test_build_decision_state():
    state = build_decision_state(
        snapshot={"code": "000725", "price": 6.08},
        report={"code": "000725", "mss_final": 51.5},
        scans=[
            {"mss_final": 50.0, "price": 5.95},
            {"mss_final": 51.5, "price": 6.08},
        ],
        lookback_mss=51.0,
        trend="rising",
    )
    assert state["mss_delta"] == 1.5
    assert "6.08" in state["recent_prices"]


def test_mock_decision_model():
    model = create_decision_model({"decision_model": {"backend": "mock"}})
    assert isinstance(model, MockDecisionModel)
    r = model.decide({"mss_final": 55, "macro_veto": 40, "aggressive_entry": 50})
    assert r.action == "buy"
    assert r.probabilities["buy"] > 0.5


def test_daily_trace_totals(trace_env):
    evt = build_late_scan_event(
        job="intraday",
        scan_id="LOCK",
        code="SYSTEM",
        name="run_guard",
        reason="busy",
    )
    append_decision_event(evt)
    totals = daily_trace_totals()
    assert totals["late_scans"] >= 1
    assert totals["day_events"] >= 1


def test_trace_jsonl_path_under_pytest(trace_env):
    p = trace_jsonl_path({"decision_trace": {}})
    assert str(trace_env) in str(p)
