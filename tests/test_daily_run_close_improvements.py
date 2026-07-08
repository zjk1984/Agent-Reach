# -*- coding: utf-8
"""Tests for close review improvement suggestions."""

from agent_reach.daily_run.close_improvements import (
    expected_scan_slots,
    generate_close_improvements,
    render_improvements_markdown,
)
from agent_reach.daily_run.settings import load_settings


def test_expected_scan_slots_count():
    slots = expected_scan_slots()
    assert len(slots) == 12
    assert slots[0]["scan_id"] == "S1"
    assert slots[1]["time"] == "08:00"


def test_generate_mss_and_schedule_improvements():
    settings = load_settings()
    baseline = {"mss_range": [40, 52], "mss_final": 48, "price": 100}
    current = {
        "mss_final": 38,
        "verdict": "观察",
        "mss_breakdown": {"technical": 42},
        "portfolio": {"cash_ratio": 0.35, "holdings": [{"code": "688008", "change_pct": -6}]},
        "watchlist": [{"code": "603986", "change_pct": -6}, {"code": "000725", "change_pct": -7}],
    }
    verify = {
        "mss_within_prediction": False,
        "mss_delta": -10,
        "verdict_current": "观察",
        "recommendations": ["维持观望"],
    }
    scans = [
        {"scan_id": "S1", "as_of": "2026-07-08T23:00:00+00:00", "mss_final": 48},
        {"scan_id": "S2", "as_of": "2026-07-08T00:00:00+00:00", "mss_final": 46, "source": "morning"},
    ]
    curve = {"trend": "震荡走弱", "prediction_hit": False, "deviation": "尾盘偏低"}

    result = generate_close_improvements(
        baseline=baseline,
        current=current,
        verify=verify,
        settings=settings,
        curve=curve,
        scans=scans,
        trades=[],
    )
    assert result.items
    cats = {i.category for i in result.items}
    assert "mss" in cats
    assert "schedule" in cats
    assert "portfolio" in cats
    assert "watchlist" in cats
    md = render_improvements_markdown(result)
    assert "复盘改进意见" in md
    assert "MSS" in md
