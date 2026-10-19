# -*- coding: utf-8
"""Tests for decision trace (jev-trader pattern)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_reach.daily_run.decision_model import MockDecisionModel, create_decision_model
from agent_reach.daily_run.decision_trace import (
    append_decision_event,
    attach_decision_closure_to_manifest_payload,
    build_decision_closure,
    build_decision_state,
    build_event_from_trade_eval,
    build_late_scan_event,
    daily_trace_totals,
    decision_trace_enabled,
    render_decision_closure_tier_a_line,
    render_decision_trace_markdown,
    trace_jsonl_path,
    validate_decision_closure,
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


def test_decision_closure_filled_apply_snapshot():
    closure = build_decision_closure(
        TradeDecision(
            action="buy",
            trade_id="T1",
            lookback_mss=50.0,
            lookback_detail=[],
            trend="rising",
            reasoning="",
            blocked=False,
        ),
        {
            "applied": True,
            "message": "ok",
            "actions": [{"side": "buy", "code": "688008", "shares": 200, "amount": 42140.0}],
        },
    )
    assert closure == {
        "decision": "buy",
        "gate": {
            "blocked": False,
            "block_kind": None,
            "guard_capped": False,
            "status": "open",
        },
        "ledger_delta": [{"side": "buy", "code": "688008", "shares": 200, "amount": 42140.0}],
        "skip_reason": None,
    }
    line = render_decision_closure_tier_a_line(closure, code="688008", name="澜起科技")
    assert "执行/gate" in line
    assert "ledger ✅" in line
    assert "688008" in line
    assert "skip:" not in line


def test_decision_closure_blocked_buy_requires_skip():
    closure = build_decision_closure(
        TradeDecision(
            action="buy",
            trade_id="T1",
            lookback_mss=51.7,
            lookback_detail=[],
            trend="rising",
            reasoning="预算不足一手",
            blocked=True,
            block_kind="buy_budget",
        ),
        {"applied": False, "message": "预算不足一手", "actions": []},
    )
    assert closure["decision"] == "buy"
    assert closure["ledger_delta"] is None
    assert closure["skip_reason"]
    assert closure["gate"]["block_kind"] == "buy_budget"
    line = render_decision_closure_tier_a_line(closure)
    assert "skip:" in line
    assert "buy_budget" in line or "预算" in line


def test_decision_closure_hold_no_skip():
    closure = build_decision_closure(
        TradeDecision(
            action="hold",
            trade_id="T0",
            lookback_mss=50.0,
            lookback_detail=[],
            trend="flat",
            reasoning="观望",
            blocked=False,
        ),
        {"applied": False, "message": "hold", "actions": []},
    )
    assert closure["skip_reason"] is None
    validate_decision_closure(closure)


def test_event_includes_closure_in_json(trace_env):
    decision = TradeDecision(
        action="sell",
        trade_id="T2",
        lookback_mss=48.0,
        lookback_detail=[],
        trend="falling",
        reasoning="止盈",
        blocked=False,
    )
    apply = type("Apply", (), {})()
    apply.to_dict = lambda: {
        "applied": True,
        "message": "sold",
        "actions": [{"side": "sell", "code": "002415", "shares": 100, "amount": 3500.0}],
        "guard_capped": False,
    }
    evt = build_event_from_trade_eval(
        job="intraday",
        scan_id="S3",
        report={"code": "002415", "name": "海康威视", "mss_final": 48.0},
        snapshot={"code": "002415", "price": 35.0},
        decision=decision,
        apply_result=apply,
        lookback_mss=48.0,
        trend="falling",
        scans=[],
    )
    payload = evt.to_dict()
    assert payload["closure"]["decision"] == "sell"
    assert payload["closure"]["ledger_delta"][0]["shares"] == 100


def test_attach_decision_closure_to_manifest_payload():
    manifest = {
        "job": "intraday",
        "result": {
            "decision_closure": {
                "decision": "hold",
                "gate": {"blocked": False, "block_kind": None, "guard_capped": False, "status": "open"},
                "ledger_delta": None,
                "skip_reason": None,
            },
            "decision_closure_line": "**执行/gate:** hold · gate=OK · ledger —",
        },
    }
    attach_decision_closure_to_manifest_payload(manifest)
    assert manifest["decision_closure"]["decision"] == "hold"
    assert manifest["decision_closure_tier_a"].startswith("**执行/gate:**")
