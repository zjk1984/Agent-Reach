# -*- coding: utf-8
"""AR-2: MSS vs TSP signal arbitration."""

from __future__ import annotations

from agent_reach.daily_run.mss_tsp_arbitration import (
    arbitrate_mss_tsp,
    attach_mss_tsp_arbitration_to_manifest,
    mss_tsp_arbitration_cfg,
    probe_tsp_session_context,
)
from agent_reach.daily_run.verdict import VerdictResult


def _buy_evaluation(mss: float = 57.0) -> dict:
    verdict = VerdictResult(
        verdict="可做",
        confidence="高",
        mss_final=mss,
        entry_price=10.0,
        stop_loss_price=9.0,
        invalidation="test",
        reasoning="MSS high",
        downgrade_reasons=[],
        blocked=False,
        label_key="buy",
    )
    report = {
        "code": "600498",
        "name": "烽火通信",
        "verdict": "可做",
        "mss_final": mss,
        "downgrade_reasons": [],
    }
    return {"verdict": verdict, "report": report}


def test_cfg_defaults_enabled():
    cfg = mss_tsp_arbitration_cfg({})
    assert cfg["enabled"] is True
    assert "retreat" in cfg["cap_verdict_on_regime_phases"]


def test_arbitrate_tsp_retreat_wins_over_mss_buy(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.mss_tsp_arbitration.probe_tsp_session_context",
        lambda *a, **k: {
            "phase": "retreat",
            "intraday_retreat": True,
            "retreat_reason": "TSP 盘中退潮急刹车",
            "mainline_hint": None,
        },
    )
    evaluation = _buy_evaluation()
    record = arbitrate_mss_tsp(evaluation, settings={"tsp_quant": {"enabled": True}})
    assert record["conflict"] is True
    assert record["winner"] == "tsp"
    assert record["rule_id"] == "tsp_intraday_retreat_over_mss_buy"
    assert evaluation["report"]["verdict"] == "观察"
    assert evaluation["verdict"].label_key == "watch"


def test_arbitrate_mainline_does_not_lift_verdict(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.mss_tsp_arbitration.probe_tsp_session_context",
        lambda *a, **k: {
            "phase": "main_up",
            "intraday_retreat": False,
            "retreat_reason": "",
            "mainline_hint": {"sector": "半导体", "score": 26.0},
        },
    )
    evaluation = _buy_evaluation()
    record = arbitrate_mss_tsp(evaluation, settings={"tsp_quant": {"enabled": True}})
    assert record["winner"] == "mss"
    assert evaluation["report"]["verdict"] == "可做"


def test_regime_retreat_caps_mss_buy(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.mss_tsp_arbitration.probe_tsp_session_context",
        lambda *a, **k: {
            "phase": "retreat",
            "phase_label": "退潮期",
            "intraday_retreat": False,
            "retreat_reason": "",
            "mainline_hint": None,
        },
    )
    evaluation = _buy_evaluation()
    record = arbitrate_mss_tsp(evaluation, settings={"tsp_quant": {"enabled": True}})
    assert record["winner"] == "tsp"
    assert evaluation["report"]["verdict"] == "观察"


def test_probe_respects_disabled_tsp():
    ctx = probe_tsp_session_context({"tsp_quant": {"enabled": False}}, job="morning")
    assert ctx.get("disabled") is True


def test_attach_manifest_rollup():
    payload = {
        "job": "intraday",
        "result": {
            "evaluation": {
                "mss_tsp_arbitration": {
                    "enabled": True,
                    "conflict": True,
                    "winner": "tsp",
                    "rule_id": "tsp_intraday_retreat_over_mss_buy",
                }
            }
        },
    }
    attach_mss_tsp_arbitration_to_manifest(payload)
    assert payload["mss_tsp_arbitration"]["conflicts"] == 1
    assert payload["mss_tsp_arbitration"]["last"]["winner"] == "tsp"