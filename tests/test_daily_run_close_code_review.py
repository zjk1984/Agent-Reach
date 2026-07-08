# -*- coding: utf-8
"""Tests for close code walkthrough and bug fixes."""

from agent_reach.daily_run.close_code_review import (
    render_code_review_markdown,
    run_close_code_review,
)
from agent_reach.daily_run.settings import load_settings


def test_auto_fix_watchlist_overlap():
    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 61000,
        "cash_ratio": 0.61,
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "days_held": 5}],
        "watchlist": [
            {"code": "688008", "name": "澜起科技"},
            {"code": "603986", "name": "兆易创新"},
        ],
    }
    snapshot = {"mss_final": 48, "watchlist": portfolio["watchlist"]}

    result = run_close_code_review(
        portfolio=portfolio,
        snapshot=snapshot,
        settings=settings,
    )
    assert result.portfolio_changed is True
    codes = {w["code"] for w in result.portfolio["watchlist"]}
    assert "688008" not in codes
    assert any("重复" in f for f in result.fixes_applied)


def test_render_code_review_markdown():
    settings = load_settings()
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
    )
    md = render_code_review_markdown(result)
    assert "代码走读" in md


def test_detect_cash_ratio_mismatch():
    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.61,
        "holdings": [],
        "watchlist": [],
    }
    result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.portfolio_changed is True
    assert abs(result.portfolio["cash_ratio"] - 0.5) < 0.001
