# -*- coding: utf-8
"""Tests for week-open overlay and forecast miss overlay."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_reach.daily_run.forecast_miss_overlay import (
    apply_forecast_miss_overlay,
    forecast_mss_miss_streak,
)
from agent_reach.daily_run.harness_policy import forecast_int_default, threshold_default
from agent_reach.daily_run.week_open_overlay import (
    apply_week_open_overlay,
    build_week_open_overlay_payload,
    classify_week_open_regime,
    save_week_open_overlay,
    week_open_overlay_active,
)

_SH = ZoneInfo("Asia/Shanghai")
_MON_AM = datetime(2026, 9, 7, 10, 0, tzinfo=_SH)


def _settings() -> dict:
    return {
        "harness": {"enabled": True, "runtime_overlay": True},
        "thresholds": {"aggressive_entry": 50.0, "macro_veto": 38.0},
        "schedule": {"trade_every_n_scans": 2},
        "week_open": {"enabled": True},
        "mss_forecast": {"base_spread": 8},
    }


def test_classify_week_open_regime_defensive_on_trim_plans():
    cfg = {
        "defensive_plan_keywords": ("减仓", "止损"),
        "supportive_plan_keywords": ("买入",),
        "defensive_plan_count": 2,
        "supportive_plan_count": 2,
        "low_confidence_pct": 50.0,
    }
    plans = [
        {"operation_plan": "减仓：跌破支撑 → 目标 10%", "confidence_pct": 60},
        {"operation_plan": "止损：MSS<45 减至 5%", "confidence_pct": 55},
    ]
    regime, _ = classify_week_open_regime(operation_plans=plans, cfg=cfg)
    assert regime == "defensive"


def test_apply_week_open_overlay_defensive_tightens_morning():
    settings = _settings()
    saved = {
        "enabled": True,
        "regime": "defensive",
        "week_start": "2026-09-07",
        "week_end": "2026-09-11",
        "plan_count": 2,
        "reasons": ["2 条偏防御操作计划"],
    }
    with (
        patch("agent_reach.daily_run.session_overlay.load_week_open_overlay", return_value=saved),
        patch("agent_reach.daily_run.session_overlay.today_shanghai", return_value=date(2026, 9, 7)),
        patch("agent_reach.daily_run.quant_calibration.load_prior_close_session_seed", return_value=None),
        patch("agent_reach.daily_run.session_overlay.load_am_open_overlay", return_value=None),
        patch("agent_reach.daily_run.overlay_telemetry.record_session_overlay"),
    ):
        patched = apply_week_open_overlay(settings, scans=[], dt=_MON_AM)

    assert week_open_overlay_active(patched)
    assert threshold_default(patched, "aggressive_entry") == 52.0


def test_build_and_save_week_open_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.week_open_overlay._HANDOFF_DIR",
        tmp_path,
    )
    payload = build_week_open_overlay_payload(
        forecast={
            "week_start": "2026-09-07",
            "week_end": "2026-09-11",
            "operation_plans": [
                {"operation_plan": "减仓：触发减仓", "confidence_pct": 40},
                {"operation_plan": "止损：跌破 118", "confidence_pct": 45},
            ],
        },
        settings={"week_open": {"enabled": True}},
    )
    path = save_week_open_overlay(payload)
    assert path.is_file()
    assert payload["regime"] == "defensive"


def test_forecast_mss_miss_streak_counts_trailing_misses():
    forecast = {
        "trading_days": ["2026-09-07", "2026-09-08", "2026-09-09"],
        "actuals": {
            "2026-09-07": {"mss_hit": True},
            "2026-09-08": {"mss_hit": False},
            "2026-09-09": {"mss_hit": False},
        },
    }
    with (
        patch(
            "agent_reach.daily_run.week_forecast.load_active_forecast",
            return_value=forecast,
        ),
        patch(
            "agent_reach.daily_run.forecast_miss_overlay.today_shanghai",
            return_value=date(2026, 9, 9),
        ),
    ):
        assert forecast_mss_miss_streak() == 2


def test_apply_forecast_miss_overlay_widens_base_spread():
    settings = _settings()
    with (
        patch(
            "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
            return_value=2,
        ),
        patch(
            "agent_reach.daily_run.forecast_miss_overlay.forecast_miss_cfg",
            return_value={
                "enabled": True,
                "min_miss_streak": 2,
                "base_spread_delta": 2,
                "max_base_spread": 14,
            },
        ),
    ):
        patched = apply_forecast_miss_overlay(settings, scans=[])

    assert forecast_int_default(patched, "base_spread") == 12
    assert (patched.get("harness_runtime") or {}).get("forecast_miss", {}).get("active")
