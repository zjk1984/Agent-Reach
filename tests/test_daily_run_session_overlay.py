# -*- coding: utf-8
"""Tests for unified session overlay."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_reach.daily_run.harness_policy import threshold_default
from agent_reach.daily_run.session_overlay import (
    apply_session_overlay,
    build_symbol_gates,
    compute_session_overlay,
    week_open_trade_block,
)

_SH = ZoneInfo("Asia/Shanghai")
_MON_AM = datetime(2026, 9, 7, 10, 0, tzinfo=_SH)
_MON_PM = datetime(2026, 9, 7, 14, 0, tzinfo=_SH)


def _settings() -> dict:
    return {
        "harness": {"enabled": True, "runtime_overlay": True},
        "thresholds": {"aggressive_entry": 50.0, "macro_veto": 38.0},
        "schedule": {"trade_every_n_scans": 2},
        "morning_open": {"enabled": True},
        "week_open": {"enabled": True},
    }


def test_build_symbol_gates_blocks_defensive_codes():
    cfg = {"defensive_plan_keywords": ("减仓", "止损")}
    gates = build_symbol_gates(
        [{"code": "300308", "operation_plan": "减仓：跌破 118 → 目标 10%"}],
        cfg=cfg,
    )
    assert gates["300308"]["block_buy"] is True


def test_unified_overlay_single_patch_morning():
    settings = _settings()
    saved_am = {
        "enabled": True,
        "regime": "defensive",
        "morning_state": {"verdict": "回避", "mss_final": 28.0},
    }
    saved_wo = {
        "enabled": True,
        "regime": "defensive",
        "week_start": "2026-09-07",
        "week_end": "2026-09-11",
        "operation_plans": [],
    }
    with (
        patch("agent_reach.daily_run.session_overlay.load_am_open_overlay", return_value=saved_am),
        patch("agent_reach.daily_run.session_overlay.load_week_open_overlay", return_value=saved_wo),
        patch("agent_reach.daily_run.quant_calibration.load_prior_close_session_seed", return_value=None),
        patch("agent_reach.daily_run.session_overlay.today_shanghai", return_value=date(2026, 9, 7)),
        patch("agent_reach.daily_run.overlay_telemetry.record_session_overlay"),
    ):
        patched = apply_session_overlay(settings, scans=[], dt=_MON_AM)
    assert threshold_default(patched, "aggressive_entry") == 52.0


def test_pm_session_merges_week_open_afternoon():
    settings = _settings()
    saved_pm = {
        "enabled": True,
        "regime": "neutral",
        "am_state": {"am_trend": "flat", "am_mss_delta": 0.0},
    }
    saved_wo = {
        "enabled": True,
        "regime": "defensive",
        "week_start": "2026-09-07",
        "week_end": "2026-09-11",
        "operation_plans": [{"code": "300308", "operation_plan": "减仓：触发"}, {"code": "002273", "operation_plan": "止损：118"}],
    }
    with (
        patch("agent_reach.daily_run.session_overlay.load_pm_session_overlay", return_value=saved_pm),
        patch("agent_reach.daily_run.session_overlay.load_week_open_overlay", return_value=saved_wo),
        patch("agent_reach.daily_run.quant_calibration.load_prior_close_session_seed", return_value=None),
        patch("agent_reach.daily_run.session_overlay.today_shanghai", return_value=date(2026, 9, 7)),
        patch("agent_reach.daily_run.session_overlay._forecast_symbol_accuracy_defensive", return_value=(False, "")),
    ):
        ctx = compute_session_overlay(settings, scans=[], dt=_MON_PM)
    assert ctx.merged_regime == "defensive"


def test_week_open_trade_block_buy():
    settings = {
        "harness_runtime": {
            "week_open": {
                "active": True,
                "symbol_gates": {
                    "300308": {"block_buy": True, "reasons": ["周日计划：减仓"]},
                },
            }
        }
    }
    assert week_open_trade_block(settings, "300308", "buy")
