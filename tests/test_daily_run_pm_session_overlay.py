# -*- coding: utf-8
"""Tests for midday AM session → afternoon intraday threshold overlay."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_reach.daily_run.harness_policy import (
    aggressive_entry_default,
    macro_veto_default,
    runtime_int_default,
    threshold_default,
)
from agent_reach.daily_run.pm_session_overlay import (
    am_session_scans,
    apply_pm_session_overlay,
    build_pm_session_overlay_payload,
    classify_pm_regime,
    compute_am_session_state,
    pm_session_overlay_active,
)
from agent_reach.daily_run.trade_calendar import is_afternoon_session

_SH = ZoneInfo("Asia/Shanghai")
_PM = datetime(2026, 8, 31, 14, 0, tzinfo=_SH)


def _settings() -> dict:
    return {
        "harness": {"enabled": True, "runtime_overlay": True},
        "thresholds": {"aggressive_entry": 50.0, "macro_veto": 38.0},
        "schedule": {"trade_every_n_scans": 2},
        "midday": {"pm_session": {"enabled": True}},
        "intraday": {"trend_min_points": 2, "trend_delta_threshold": 1.0},
    }


def test_am_session_scans_skip_midday_and_afternoon():
    scans = [
        {"scan_id": "S6", "mss_final": 52.0},
        {"scan_id": "S7", "mss_final": 48.0},
        {"scan_id": "S8", "mss_final": 46.0, "source": "midday", "trend_excluded": True},
        {"scan_id": "S9", "mss_final": 50.0},
    ]
    am = am_session_scans(scans)
    assert [s["scan_id"] for s in am] == ["S6", "S7"]


def test_classify_defensive_on_weak_am_trend():
    cfg = {
        "weak_am_trends": ("falling", "turning_down"),
        "weak_am_mss_delta": -5.0,
        "halfday_loss_pct": -0.3,
        "red_anomaly_count": 2,
        "supportive_am_trends": ("rising", "turning_up"),
        "supportive_am_mss_delta": 5.0,
    }
    state = {"am_trend": "falling", "am_mss_delta": -2.0, "red_anomaly_count": 0}
    assert classify_pm_regime(state, cfg) == "defensive"


def test_apply_pm_session_overlay_defensive_tightens_afternoon_thresholds():
    settings = _settings()
    saved = {
        "enabled": True,
        "regime": "defensive",
        "am_state": {
            "am_trend": "falling",
            "am_mss_delta": -8.0,
            "halfday_pnl_pct": -0.5,
            "red_anomaly_count": 1,
        },
    }
    with (
        patch("agent_reach.daily_run.session_overlay.load_pm_session_overlay", return_value=saved),
        patch("agent_reach.daily_run.quant_calibration.load_prior_close_session_seed", return_value=None),
        patch("agent_reach.daily_run.week_open_overlay.load_week_open_overlay", return_value=None),
        patch("agent_reach.daily_run.session_overlay._forecast_symbol_accuracy_defensive", return_value=(False, "")),
        patch("agent_reach.daily_run.overlay_telemetry.record_session_overlay"),
    ):
        patched = apply_pm_session_overlay(settings, scans=[], dt=_PM)

    assert pm_session_overlay_active(patched)
    assert threshold_default(patched, "aggressive_entry") == aggressive_entry_default(settings) + 3.0
    assert threshold_default(patched, "macro_veto") == macro_veto_default(settings) + 2.0
    assert runtime_int_default(patched, "schedule", "trade_every_n_scans") == 3


def test_apply_pm_session_overlay_skipped_outside_afternoon():
    settings = _settings()
    saved = {"enabled": True, "regime": "defensive", "am_state": {"am_trend": "falling"}}
    lunch = datetime(2026, 8, 31, 12, 30, tzinfo=_SH)
    with patch(
        "agent_reach.daily_run.pm_session_overlay.load_pm_session_overlay",
        return_value=saved,
    ):
        patched = apply_pm_session_overlay(settings, scans=[], dt=lunch)
    assert patched is settings
    assert not pm_session_overlay_active(patched)


def test_build_pm_session_overlay_payload():
    scans = [
        {"scan_id": "S6", "mss_final": 55.0},
        {"scan_id": "S7", "mss_final": 48.0},
    ]
    payload = build_pm_session_overlay_payload(
        scans=scans,
        settings=_settings(),
        halfday_pnl_pct=-0.4,
        red_anomaly_count=2,
        lookback_mss=50.0,
        anchor_trend="falling",
    )
    assert payload["regime"] == "defensive"
    assert payload["am_state"]["red_anomaly_count"] == 2


def test_is_afternoon_session_window():
    assert is_afternoon_session(_PM)
    assert not is_afternoon_session(datetime(2026, 8, 31, 11, 0, tzinfo=_SH))
