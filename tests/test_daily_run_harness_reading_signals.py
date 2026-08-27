# -*- coding: utf-8
"""Tests for harness reading-driven MSS recovery signals."""

import json
from pathlib import Path

from agent_reach.daily_run.harness import HarnessEntry, HarnessState
from agent_reach.daily_run.harness_policy import (
    _apply_mss_signal_evolution,
    resolve_harness_trade_signals,
)
from agent_reach.daily_run.harness_reading_signals import (
    merge_reading_into_trade_signals,
    resolve_harness_reading_signals,
)


def _write_intraday_state(tmp_path: Path, scans: list[dict]) -> None:
    state_path = tmp_path / "intraday_state.json"
    state_path.write_text(
        json.dumps({"date": "2026-08-27", "scans": scans, "trades": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_reading_recovery_suppresses_stale_mss_defense(tmp_path, monkeypatch):
    scans = [
        {"scan_id": "S6", "mss_final": 48.0},
        {"scan_id": "S7", "mss_final": 51.0},
        {"scan_id": "S8", "mss_final": 55.0},
    ]
    _write_intraday_state(tmp_path, scans)
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        lambda code=None: tmp_path / "intraday_state.json",
    )
    monkeypatch.setattr("agent_reach.daily_run.intraday._today_str", lambda: "2026-08-27")

    state = HarnessState()
    state.entries["memory"]["miss"] = HarnessEntry(
        id="miss",
        kind="memory",
        title="MSS 预测偏离",
        content="MSS 预测偏离：下日调低进攻阈值或缩窄仓位",
        source="deterministic",
        job="close",
        evidence="close",
        created_at="2026-08-17T00:00:00+00:00",
        updated_at="2026-08-17T00:00:00+00:00",
    )
    settings = {
        "harness": {
            "runtime_overlay_sources": ["memory"],
            "reading_signals": {"enabled": True},
        },
        "intraday": {"trend_min_points": 2, "trend_delta_threshold": 1.0},
    }
    reading = resolve_harness_reading_signals(settings)
    assert reading.get("mss_recovery") is True

    signals = resolve_harness_trade_signals(state, settings=settings)
    assert signals.get("defensive_trim") is False
    assert signals.get("macro_warming") is True

    merged = _apply_mss_signal_evolution(
        {"macro_veto": 40.0, "aggressive_entry": 50.0},
        state,
        settings=settings,
    )
    assert merged["macro_veto"] >= 38.0
    assert merged["aggressive_entry"] >= 48.0


def test_reading_keeps_pnl_miss_defense(tmp_path, monkeypatch):
    _write_intraday_state(
        tmp_path,
        [
            {"scan_id": "S6", "mss_final": 48.0},
            {"scan_id": "S7", "mss_final": 54.0},
            {"scan_id": "S8", "mss_final": 56.0},
        ],
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        lambda code=None: tmp_path / "intraday_state.json",
    )
    monkeypatch.setattr("agent_reach.daily_run.intraday._today_str", lambda: "2026-08-27")

    memory = {
        "mss_forecast_miss": True,
        "defensive_trim": True,
        "deviation_active": True,
        "pnl_target_miss": True,
    }
    reading = resolve_harness_reading_signals({"harness": {"reading_signals": {"enabled": True}}})
    out = merge_reading_into_trade_signals(memory, reading, settings={"harness": {"reading_signals": {}}})
    assert out.get("defensive_trim") is True
    assert out.get("mss_forecast_miss") is False
