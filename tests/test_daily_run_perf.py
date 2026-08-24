# -*- coding: utf-8
"""Tests for daily-run perf helpers."""

from agent_reach.daily_run.settings import clear_settings_cache, load_settings
from agent_reach.daily_run.symbols import build_enriched_symbols


def test_settings_cache_returns_same_data():
    clear_settings_cache()
    a = load_settings()
    b = load_settings()
    assert a == b
    assert a is not b


def test_build_enriched_symbols_merges_holdings_and_watchlist():
    snap = {
        "code": "688008",
        "price": 100,
        "portfolio": {"holdings": [{"code": "688008", "price": 100}]},
        "watchlist": [{"code": "603986", "change_pct": -1}],
    }
    m = build_enriched_symbols(snap)
    assert "688008" in m
    assert "603986" in m


def test_build_enriched_symbols_carries_volume_and_turnover():
    """M4: primary-code volume/turnover must reach the map for suspension checks."""
    snap = {
        "code": "688008",
        "price": 100,
        "volume": 0,
        "turnover": 0,
        "portfolio": {"holdings": [{"code": "688008", "price": 100}]},
        "watchlist": [],
    }
    m = build_enriched_symbols(snap)
    assert m["688008"]["volume"] == 0
    assert m["688008"]["turnover"] == 0
