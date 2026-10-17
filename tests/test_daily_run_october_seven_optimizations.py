# -*- coding: utf-8
"""October 2026 seven trading optimizations."""

from __future__ import annotations

from agent_reach.daily_run.defensive_trim_guards import (
    defensive_trim_blocked_by_recovery_zone,
    mss_warmth_buy_block_reason,
)
from agent_reach.daily_run.forecast_miss_overlay import apply_forecast_miss_overlay
from agent_reach.daily_run.intraday_min_cash import effective_intraday_min_cash_ratio
from agent_reach.daily_run.intraday_policy import intraday_audit_block_reason
from agent_reach.daily_run.watchlist_manager import (
    WatchlistChange,
    _evict_low_score_watchlist_at_total_cap,
    adjust_watchlist,
)


def test_min_cash_relax_when_mss_high_and_no_tsp_retreat(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday_min_cash.tsp_retreat_blocks_min_cash_relax",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy.min_cash_ratio_default",
        lambda settings: 0.5,
    )
    settings = {
        "technical_watch": {
            "min_cash_ratio_cap": {
                "enabled": True,
                "register_min_cash_ratio": 0.5,
                "relax_delta": 0.02,
                "rebound_mss_level": 55.0,
                "attack_min_cash_ratio": 0.35,
            }
        }
    }
    effective, note = effective_intraday_min_cash_ratio(settings, lookback_mss=56.0)
    assert effective == 0.35
    assert note is not None


def test_audit_fail_blocks_buy_not_sell():
    report = {"audit_passed": False}
    settings = {"harness_runtime": {"intraday_audit_policy": {"intraday_block_on_audit_fail": 1.0}}}
    assert intraday_audit_block_reason(settings, report, trade_side="buy")
    assert intraday_audit_block_reason(settings, report, trade_side="sell") is None


def test_warmth_gates_buy_and_memory_trim_recovery_guard():
    settings = {"harness": {"reading_signals": {"recovery_min_lookback": 50.0}}}
    buy_block = mss_warmth_buy_block_reason(
        settings,
        lookback_mss=48.0,
        trade_signals={"defensive_trim": True},
    )
    assert buy_block is not None
    sell_block = defensive_trim_blocked_by_recovery_zone(
        settings,
        lookback_mss=55.0,
        trade_signals={"defensive_trim": True, "mss_forecast_miss": True},
    )
    assert sell_block is not None
    assert "回暖线" in sell_block
    below_line = defensive_trim_blocked_by_recovery_zone(
        settings,
        lookback_mss=48.0,
        trade_signals={"defensive_trim": True, "mss_forecast_miss": True},
    )
    assert below_line is None


def test_forecast_miss_overlay_widens_on_hit_rate(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
        lambda **k: 0,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.quant_calibration.forecast_hit_rate_gate",
        lambda **k: (False, "low hit rate"),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy.forecast_int_default",
        lambda settings, key: 8,
    )
    out = apply_forecast_miss_overlay({"mss_forecast": {"base_spread": 8}})
    assert out["mss_forecast"]["base_spread"] >= 10


def test_watchlist_evict_low_score_at_total_cap():
    settings = {
        "watchlist": {"min_size": 5, "max_size": 7, "auto_adjust_enabled": True},
        "portfolio": {"max_total_symbols": 10},
        "thresholds": {"macro_veto": 30},
    }
    pf = {
        "holdings": [
            {"code": "600001", "name": "A", "shares": 100},
            {"code": "600010", "name": "J", "shares": 100},
            {"code": "600011", "name": "K", "shares": 100},
        ],
        "watchlist": [
            {"code": "600002", "name": "B"},
            {"code": "600003", "name": "C"},
            {"code": "600004", "name": "D"},
            {"code": "600005", "name": "E"},
            {"code": "600006", "name": "F"},
            {"code": "600007", "name": "G"},
            {"code": "600008", "name": "H"},
        ],
    }
    enriched = {
        **{f"60000{i}": {"mss_final": 40 + i, "change_pct": 0.0} for i in range(2, 9)},
        "600001": {"mss_final": 50, "change_pct": 0.0},
        "600010": {"mss_final": 50, "change_pct": 0.0},
        "600011": {"mss_final": 50, "change_pct": 0.0},
    }
    changes: list[WatchlistChange] = []
    held = {"600001", "600010", "600011"}
    before = len(pf["watchlist"])
    _evict_low_score_watchlist_at_total_cap(
        pf,
        enriched,
        settings,
        changes,
        held_codes=held,
        base_mss=50.0,
    )
    assert len(pf["watchlist"]) < before
    assert changes
