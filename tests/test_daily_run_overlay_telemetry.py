# -*- coding: utf-8
"""Tests for overlay telemetry v2 merge, aggregate, and storage hooks."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from agent_reach.daily_run.overlay_telemetry import (
    _coerce_v2_record,
    _merge_snapshot_into_daily,
    _new_daily_record,
    _snapshot_from_ctx,
    aggregate_week_overlay_stats,
    record_session_overlay,
    render_week_overlay_stats_markdown,
)
from agent_reach.daily_run.session_overlay import SessionOverlayContext

_SH = ZoneInfo("Asia/Shanghai")


def test_merge_same_day_morning_and_afternoon():
    day = date(2026, 9, 1)
    daily = _new_daily_record(day)
    morning_snap = _snapshot_from_ctx(
        {},
        SessionOverlayContext(session="morning", merged_regime="defensive", session_regime="defensive"),
        scan_at="2026-09-01T10:00:00+08:00",
    )
    afternoon_snap = _snapshot_from_ctx(
        {},
        SessionOverlayContext(session="afternoon", merged_regime="neutral", session_regime="neutral"),
        scan_at="2026-09-01T14:00:00+08:00",
    )
    daily = _merge_snapshot_into_daily(daily, morning_snap)
    daily = _merge_snapshot_into_daily(daily, afternoon_snap)

    assert daily["morning"]["seen"] is True
    assert daily["morning"]["scan_count"] == 1
    assert daily["afternoon"]["seen"] is True
    assert daily["afternoon"]["scan_count"] == 1
    assert daily["day_merged_regime"] == "defensive"
    assert daily["day_threshold_patched"] is True


def test_coerce_v1_to_v2():
    day = date(2026, 9, 1)
    v1 = {
        "date": "2026-09-01",
        "session": "morning",
        "merged_regime": "supportive",
        "symbol_gate_count": 2,
    }
    v2 = _coerce_v2_record(v1, day)
    assert v2["version"] == 2
    assert v2["morning"]["seen"] is True
    assert v2["morning"]["last_merged_regime"] == "supportive"
    assert v2["symbol_gate_count_max"] == 2


def test_record_session_overlay_merges_file(tmp_path, monkeypatch):
    log_dir = tmp_path / "overlay_log"
    monkeypatch.setattr(
        "agent_reach.daily_run.overlay_telemetry._log_dir",
        lambda: log_dir,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.overlay_telemetry.today_shanghai",
        lambda: date(2026, 9, 1),
    )
    settings = {"overlay_telemetry": {"dual_write_db": False}}

    ctx_m = SessionOverlayContext(session="morning", merged_regime="defensive", session_regime="defensive")
    record_session_overlay(settings, ctx_m)
    ctx_a = SessionOverlayContext(session="afternoon", merged_regime="neutral", session_regime="neutral")
    record_session_overlay(settings, ctx_a)

    saved = (log_dir / "2026-09-01.json").read_text(encoding="utf-8")
    assert "morning" in saved
    assert '"seen": true' in saved
    import json

    row = json.loads(saved)
    assert row["morning"]["scan_count"] == 1
    assert row["afternoon"]["scan_count"] == 1


def test_aggregate_week_stats_from_files(tmp_path, monkeypatch):
    log_dir = tmp_path / "overlay_log"
    log_dir.mkdir()
    day = date(2026, 9, 1)
    daily = _new_daily_record(day)
    daily["morning"]["seen"] = True
    daily["morning"]["scan_count"] = 2
    daily["day_merged_regime"] = "defensive"
    daily["day_threshold_patched"] = True
    import json

    (log_dir / f"{day.isoformat()}.json").write_text(
        json.dumps(daily, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_reach.daily_run.overlay_telemetry._log_dir", lambda: log_dir)
    monkeypatch.setattr(
        "agent_reach.daily_run.overlay_telemetry._trading_days_in_range",
        lambda ws, we, settings=None: [day],
    )

    stats = aggregate_week_overlay_stats(day, day, settings={"overlay_telemetry": {"read_prefer_db": False}})
    assert stats["log_days"] == 1
    assert stats["morning_overlay_days"] == 1
    assert stats["defensive_days"] == 1
    assert stats["threshold_patch_days"] == 1
    assert stats["source"] == "file"


def test_render_markdown_shows_coverage():
    lines = render_week_overlay_stats_markdown(
        {
            "trading_days_in_range": 5,
            "log_days": 4,
            "days": 4,
            "coverage_pct": 0.8,
            "data_quality": "partial",
            "threshold_patch_days": 2,
            "defensive_days": 2,
            "supportive_days": 1,
            "morning_overlay_days": 4,
            "afternoon_overlay_days": 3,
            "symbol_gate_days": 1,
            "forecast_accuracy_defensive_days": 0,
        }
    )
    body = "\n".join(lines)
    assert "覆盖" in body
    assert "80%" in body
    assert "partial" in body


def test_quant_chain_doctor_runs():
    from agent_reach.daily_run.quant_chain_doctor import run_quant_chain_doctor

    report = run_quant_chain_doctor(as_of=date(2026, 9, 6))
    assert report["status"] in ("ok", "warn", "error")
    assert len(report["checks"]) >= 4
