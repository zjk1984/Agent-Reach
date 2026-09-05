# -*- coding: utf-8
"""Tests for morning open intraday threshold overlay."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_reach.daily_run.am_open_overlay import (
    am_open_overlay_active,
    apply_am_open_overlay,
    build_am_open_overlay_payload,
    classify_am_open_regime,
)
from agent_reach.daily_run.harness_policy import (
    aggressive_entry_default,
    macro_veto_default,
    runtime_int_default,
    threshold_default,
)
from agent_reach.daily_run.trade_calendar import is_morning_session

_SH = ZoneInfo("Asia/Shanghai")
_AM = datetime(2026, 8, 31, 10, 0, tzinfo=_SH)


def _settings() -> dict:
    return {
        "harness": {"enabled": True, "runtime_overlay": True},
        "thresholds": {"aggressive_entry": 50.0, "macro_veto": 38.0},
        "schedule": {"trade_every_n_scans": 2},
        "morning_open": {"enabled": True},
    }


def test_classify_defensive_on_avoid_verdict():
    cfg = {
        "defensive_verdicts": ("回避",),
        "supportive_verdicts": ("可做",),
        "high_cash_ratio": 0.45,
        "weak_mss_below_veto_buffer": 0.0,
        "supportive_mss_above_aggressive": 0.0,
    }
    state = {"verdict": "回避", "mss_final": 55.0}
    assert classify_am_open_regime(state, cfg, settings=_settings()) == "defensive"


def test_apply_am_open_overlay_defensive_tightens_morning_thresholds():
    settings = _settings()
    saved = {
        "enabled": True,
        "regime": "defensive",
        "morning_state": {"verdict": "回避", "mss_final": 28.0},
    }
    with (
        patch("agent_reach.daily_run.session_overlay.load_am_open_overlay", return_value=saved),
        patch("agent_reach.daily_run.session_overlay.load_week_open_overlay", return_value=None),
        patch("agent_reach.daily_run.quant_calibration.load_prior_close_session_seed", return_value=None),
        patch("agent_reach.daily_run.overlay_telemetry.record_session_overlay"),
    ):
        patched = apply_am_open_overlay(settings, scans=[], dt=_AM)

    assert am_open_overlay_active(patched)
    assert threshold_default(patched, "aggressive_entry") == aggressive_entry_default(settings) + 2.0
    assert threshold_default(patched, "macro_veto") == macro_veto_default(settings) + 2.0
    assert runtime_int_default(patched, "schedule", "trade_every_n_scans") == 3


def test_apply_am_open_overlay_skipped_outside_morning_session():
    settings = _settings()
    saved = {"enabled": True, "regime": "defensive", "morning_state": {"verdict": "回避"}}
    lunch = datetime(2026, 8, 31, 12, 30, tzinfo=_SH)
    with (
        patch("agent_reach.daily_run.am_open_overlay.load_am_open_overlay", return_value=saved),
        patch("agent_reach.daily_run.session_overlay.load_pm_session_overlay", return_value=None),
        patch("agent_reach.daily_run.week_open_overlay.load_week_open_overlay", return_value=None),
        patch("agent_reach.daily_run.overlay_telemetry.record_session_overlay"),
    ):
        patched = apply_am_open_overlay(settings, scans=[], dt=lunch)
    assert patched is settings
    assert not am_open_overlay_active(patched)


def test_build_am_open_overlay_payload_supportive():
    payload = build_am_open_overlay_payload(
        mss_final=52.0,
        verdict="可做",
        cash_ratio=0.2,
        settings=_settings(),
    )
    assert payload["regime"] == "supportive"
    assert payload["morning_state"]["mss_final"] == 52.0


def test_is_morning_session_window():
    assert is_morning_session(_AM)
    assert not is_morning_session(datetime(2026, 8, 31, 9, 0, tzinfo=_SH))
