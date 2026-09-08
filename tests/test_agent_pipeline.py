# -*- coding: utf-8
"""Tests for AutoHedge-inspired agent pipeline."""

from __future__ import annotations

from agent_reach.daily_run.agent_pipeline import (
    build_execution_intent,
    build_pipeline_handoff,
    build_quant_analysis,
    build_risk_assessment,
    build_thesis,
    discover_symbols_from_task,
)
from agent_reach.daily_run.expert_tool_registry import channel_allowed, list_expert_channels


def test_discover_symbols_from_task_codes_and_names():
    pf = {
        "holdings": [{"code": "300308", "name": "中际旭创"}],
        "watchlist": [{"code": "601138", "name": "工业富联"}],
    }
    codes = discover_symbols_from_task('分析 ["300308","601138"] 和 中际旭创', portfolio=pf)
    assert "300308" in codes
    assert "601138" in codes


def test_pipeline_handoff_schema():
    snapshot = {
        "code": "300308",
        "name": "中际旭创",
        "mss_final": 52.0,
        "mss_breakdown": {"technical": 55, "quant": 50, "risk": 48, "flow": 60},
        "expert_scores": {"technical": 55, "quant": 50, "risk": 48, "sentiment": 60},
        "expert_results": [
            {"name": "quant", "score": 50, "summary": "quant ok", "success": True},
            {"name": "risk", "score": 48, "summary": "risk tight", "success": True},
        ],
    }
    evaluation = {
        "report": {
            "code": "300308",
            "name": "中际旭创",
            "verdict": "可做",
            "confidence": "中",
            "mss_final": 52.0,
            "blocked": False,
            "reasoning": "MSS 达标",
            "entry_price": 120.0,
            "stop_loss_price": 110.0,
        }
    }
    handoff = build_pipeline_handoff(snapshot, evaluation, workflow="morning", task="分析中际旭创")
    assert handoff["schema_version"] == 1
    assert handoff["thesis"]["code"] == "300308"
    assert handoff["quant_analysis"]["probability_score"] is not None
    assert handoff["risk_assessment"]["risk_score"] is not None
    assert handoff["execution_intent"]["action"] == "buy"


def test_expert_tool_registry_isolation():
    assert channel_allowed("sentiment", "exa") is True
    assert channel_allowed("sentiment", "xueqiu") is True
    assert channel_allowed("quant", "exa") is False
    assert channel_allowed("macro", "exa") is True
    assert channel_allowed("macro", "xueqiu") is False
    assert "exa" in list_expert_channels("sentiment")


def test_execution_hold_when_blocked():
    snapshot = {"portfolio": {"cash_ratio": 0.5}}
    report = {"verdict": "观察", "blocked": True, "mss_final": 40}
    quant = build_quant_analysis(snapshot, report)
    risk = build_risk_assessment(snapshot, report, quant)
    execution = build_execution_intent(snapshot, report, risk, workflow="intraday")
    assert execution["action"] == "hold"
    assert execution["blocked"] is True


def test_build_thesis_includes_team_review():
    snapshot = {
        "code": "688008",
        "team_review": {"consensus_label": "观察", "consensus_score": 49.0},
    }
    report = {"code": "688008", "name": "澜起科技", "verdict": "观察", "reasoning": "test"}
    thesis = build_thesis(snapshot, report, task="task")
    assert thesis["code"] == "688008"
    assert any("team=" in f for f in thesis["key_factors"])
