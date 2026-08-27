# -*- coding: utf-8
"""Tests for lunch-break scan filtering and midday MSS anchoring."""

from datetime import datetime
from zoneinfo import ZoneInfo

from agent_reach.daily_run.intraday_scan_filters import (
    merge_midday_breakdown,
    preserve_session_price_fields,
    scans_for_trend_detection,
)
from agent_reach.daily_run.lookback import compute_lookback_mss, detect_mss_trend
from agent_reach.daily_run.trade_calendar import is_lunch_break

_SH = ZoneInfo("Asia/Shanghai")


def test_is_lunch_break():
    assert is_lunch_break(datetime(2026, 8, 27, 12, 30, tzinfo=_SH)) is True
    assert is_lunch_break(datetime(2026, 8, 27, 11, 29, tzinfo=_SH)) is False
    assert is_lunch_break(datetime(2026, 8, 27, 13, 0, tzinfo=_SH)) is False


def test_merge_midday_breakdown_keeps_technical():
    base = {"fx": 50, "flow": 52, "technical": 58, "quant": 57, "risk": 55}
    live = {"fx": 46, "flow": 44, "global": 46, "sentiment": 46, "technical": 40, "quant": 40}
    merged = merge_midday_breakdown(base, live)
    assert merged["flow"] == 44
    assert merged["technical"] == 58
    assert merged["quant"] == 57


def test_scans_for_trend_detection_excludes_midday_anchor():
    scans = [
        {"scan_id": "S6", "mss_final": 54.0},
        {"scan_id": "S7", "mss_final": 55.0},
        {"scan_id": "S8", "mss_final": 46.67, "source": "midday", "trend_excluded": True},
    ]
    filtered = scans_for_trend_detection(scans)
    assert [s["scan_id"] for s in filtered] == ["S6", "S7"]


def test_midday_dip_does_not_force_turning_down():
    scans = [
        {"scan_id": "S6", "mss_final": 52.0},
        {"scan_id": "S7", "mss_final": 55.0},
        {
            "scan_id": "S8",
            "mss_final": 46.67,
            "source": "midday",
            "trend_excluded": True,
            "lookback_weight_scale": 0.25,
        },
    ]
    settings = {"harness": {"enabled": False}, "intraday": {"trend_min_points": 2, "trend_delta_threshold": 1.0}}
    assert detect_mss_trend(scans, settings) == "rising"


def test_lookback_downweights_midday_anchor():
    scans = [
        {"scan_id": "S7", "mss_final": 55.0},
        {
            "scan_id": "S8",
            "mss_final": 46.67,
            "source": "midday",
            "trend_excluded": True,
            "lookback_weight_scale": 0.25,
        },
    ]
    settings = {"harness": {"enabled": False}}
    lookback, detail = compute_lookback_mss(scans, settings)
    assert lookback > 50.0
    assert detail[0].get("anchor") is True


def test_preserve_session_price_fields():
    snapshot = {"price": None, "mss_breakdown": {"flow": 44}}
    session = {
        "mss_final": 55.0,
        "price": 21.5,
        "mss_breakdown": {"technical": 58, "quant": 57, "risk": 55, "flow": 52},
    }
    out = preserve_session_price_fields(snapshot, session)
    assert out["price"] == 21.5
    assert out["mss_breakdown"]["technical"] == 58
