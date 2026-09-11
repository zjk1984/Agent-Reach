# -*- coding: utf-8
"""Tests for Qlib-inspired daily-run modules."""

from __future__ import annotations

from agent_reach.daily_run.drift_trigger import evaluate_drift, drift_trade_block_reason
from agent_reach.daily_run.execution_quality import compute_execution_quality
from agent_reach.daily_run.experiment_recorder import load_experiment_registry, record_experiment
from agent_reach.daily_run.nested_decision import build_nested_decision
from agent_reach.daily_run.pit_guard import audit_snapshot_pit, pit_guard_block_reason
from agent_reach.daily_run.risk_panel import build_risk_panel, merge_risk_panel_into_metrics


def test_pit_guard_flags_signal_lag_and_future_macro():
    snapshot = {
        "as_of": "2026-09-10T10:00:00+08:00",
        "report_type": "intraday",
        "morning_baseline_same_day": True,
        "macro_ctx": {"as_of": "2026-09-10T11:00:00+08:00"},
    }
    result = audit_snapshot_pit(snapshot, job="intraday", settings={"pit_guard": {"enabled": True}})
    assert result["ok"] is False
    assert result["finding_count"] >= 2

    snapshot["pit_guard"] = result
    block = pit_guard_block_reason(snapshot, settings={"pit_guard": {"enabled": True, "block_on_fail": True}})
    assert block is not None
    assert block.startswith("pit_guard")


def test_execution_quality_pa_ffr_pos():
    trades = [
        {
            "action": "buy",
            "portfolio_applied": True,
            "requested_shares": 100,
            "filled_shares": 100,
            "signal_price": 10.0,
            "execution_price": 9.98,
        },
        {
            "action": "sell",
            "portfolio_applied": True,
            "requested_shares": 50,
            "filled_shares": 40,
            "signal_price": 11.0,
            "execution_price": 10.95,
            "realized_pnl": 120.0,
        },
    ]
    result = compute_execution_quality(trades, settings={"execution_quality": {"enabled": True}})
    assert result.get("skipped") is False
    assert result["fill_rate"] == 0.9
    assert result["price_advantage_bps"] is not None
    assert result["positive_rate_pct"] == 100.0


def test_experiment_recorder_append(tmp_path, monkeypatch):
    reg_path = tmp_path / "registry.json"

    monkeypatch.setattr(
        "agent_reach.daily_run.experiment_recorder.experiments_dir",
        lambda settings=None: tmp_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.experiment_recorder._registry_path",
        lambda settings=None: reg_path,
    )

    entry = record_experiment(
        job="hyperopt_lite",
        params={"deploy_ratio": 0.25},
        metrics={"loss": 1.2},
        settings={"experiment_recorder": {"enabled": True, "jobs": ["hyperopt_lite"]}},
    )
    assert entry is not None
    data = load_experiment_registry(
        settings={"experiment_recorder": {"enabled": True, "jobs": ["hyperopt_lite"]}}
    )
    assert len(data["experiments"]) == 1


def test_nested_decision_layers():
    nested = build_nested_decision(
        signal_verdict="可做",
        signal_blocked=False,
        signal_reason="",
        risk_verdict="blocked",
        risk_blocked=True,
        risk_reason="protection_buy",
        execution_action="hold",
        execution_blocked=True,
        execution_reason="sector mismatch",
        settings={"nested_decision": {"enabled": True}},
        extra={"lookback_mss": 52.0, "block_kind": "protection_buy"},
    )
    assert nested["enabled"] is True
    assert len(nested["layers"]) == 3
    assert nested["final_blocked"] is True


def test_risk_panel_alerts_on_drawdown():
    risk_metrics = {"max_drawdown_pct": -6.5, "volatility_ann_pct": 18.0, "win_rate_pct": 40.0}
    panel = build_risk_panel(
        risk_metrics=risk_metrics,
        settings={"risk_panel": {"enabled": True, "max_drawdown_alert_pct": 5.0}},
    )
    assert panel.get("skipped") is False
    assert panel["alerts"]

    merged = merge_risk_panel_into_metrics(risk_metrics, settings={"risk_panel": {"enabled": True}})
    assert "risk_panel" in merged


def test_drift_trigger_weekly_pnl_and_mss():
    report = {"weekly_pnl_pct": -3.0, "planned_mss": 55.0, "mss_final": 50.0}
    drift = evaluate_drift(
        report=report,
        settings={
            "drift_trigger": {
                "enabled": True,
                "weekly_pnl_alert_pct": -2.0,
                "mss_drift_pts": 3.0,
                "block_trade_on_trigger": True,
            }
        },
    )
    assert drift["triggered"] is True
    assert len(drift["reasons"]) >= 2
    block = drift_trade_block_reason(
        report=report,
        settings={
            "drift_trigger": {
                "enabled": True,
                "weekly_pnl_alert_pct": -2.0,
                "mss_drift_pts": 3.0,
                "block_trade_on_trigger": True,
            }
        },
    )
    assert block is not None
