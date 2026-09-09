# -*- coding: utf-8
"""Tests for sector gap-down macro buffer."""

from agent_reach.daily_run.sector_gap_guard import (
    detect_sector_gap_down_fade,
    intraday_macro_veto_with_sector_buffer,
)


def test_detect_semiconductor_gap_down_fade():
    fade = detect_sector_gap_down_fade(
        {
            "portfolio": {
                "holdings": [
                    {
                        "code": "688981",
                        "name": "中芯国际",
                        "shares": 100,
                        "sector": "半导体",
                        "open": 52.0,
                        "prev_close": 50.0,
                        "change_pct": -0.5,
                    }
                ]
            }
        },
        settings={
            "intraday": {
                "sector_gap_guard": {
                    "min_open_gap_pct": 0.8,
                    "min_fade_pct": 2.0,
                }
            }
        },
    )
    assert fade is not None
    assert fade["sector"] == "半导体"
    assert fade["fade_pct"] >= 2.0


def test_macro_veto_bump_on_sector_gap_down():
    effective, note = intraday_macro_veto_with_sector_buffer(
        30.0,
        {
            "portfolio": {
                "holdings": [
                    {
                        "code": "688981",
                        "name": "中芯国际",
                        "shares": 100,
                        "sector": "半导体",
                        "open": 52.0,
                        "prev_close": 50.0,
                        "change_pct": -0.5,
                    }
                ]
            }
        },
        settings={"intraday": {"sector_gap_guard": {"macro_veto_bump": 3.0}}},
    )
    assert effective == 33.0
    assert note is not None
    assert "macro_veto" in note
