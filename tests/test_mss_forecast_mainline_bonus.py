# -*- coding: utf-8
"""Mainline rotation spread bonus for MSS forecast."""

from __future__ import annotations

from agent_reach.daily_run.mss_forecast import forecast_mss_range


def test_mainline_rotation_widens_spread():
    settings = {
        "mss_weights": {"fx": 0.2, "flow": 0.2, "global": 0.2, "sentiment": 0.2, "technical": 0.2},
        "mss_forecast": {
            "simulations": 50,
            "mainline_rotation_enabled": True,
            "mainline_rotation_spread_bonus": 4.0,
        },
    }
    base_snapshot = {
        "code": "002583",
        "sector": "通信设备",
        "mss_final": 50.0,
        "mss_breakdown": {"fx": 50, "flow": 50, "global": 50, "sentiment": 50, "technical": 50},
        "change_pct": 1.0,
    }
    _, meta_plain = forecast_mss_range(base_snapshot, settings)
    with_mainline = {
        **base_snapshot,
        "tsp_intraday": {
            "top_mainlines": [{"name": "通信设备", "limit_up_count": 5, "score": 80}],
        },
    }
    _, meta_main = forecast_mss_range(with_mainline, settings)
    assert meta_main["mainline_rotation_spread_bonus"] == 4.0
    assert meta_plain.get("mainline_rotation_spread_bonus", 0) == 0.0
    assert meta_main["median"] != meta_plain["median"] or (
        with_mainline["tsp_intraday"] and meta_main["mainline_rotation_spread_bonus"] > 0
    )
