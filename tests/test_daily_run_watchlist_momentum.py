# -*- coding: utf-8
"""Tests for watchlist momentum score boost."""

from agent_reach.daily_run.watchlist_momentum import watchlist_momentum_score_boost


def test_strong_day_actionable_verdict_boosts_score():
    boost = watchlist_momentum_score_boost(
        {"code": "603986", "change_pct": 3.5, "verdict": "可做", "mss_final": 55},
        settings={"thresholds": {"aggressive_entry": 45}},
    )
    assert boost >= 1.5


def test_weak_day_no_boost():
    boost = watchlist_momentum_score_boost(
        {"code": "603986", "change_pct": 0.5, "verdict": "可做", "mss_final": 55},
        settings={"watchlist": {"momentum_score": {"strong_day_pct": 2.0}}},
    )
    assert boost == 0.0
