# -*- coding: utf-8
"""M7: portfolio quote coverage, fallback meta, watchlist adjust manifest."""

from __future__ import annotations

from agent_reach.daily_run.close_cards import CloseCardContext, render_close_summary_markdown
from agent_reach.daily_run.quote_coverage import (
    enrich_quote_fetch_meta,
    portfolio_quote_coverage,
)
from agent_reach.daily_run.quote_fetch import QuoteFetchResult
import pytest

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.watchlist_manager import (
    WatchlistAdjustResult,
    adjust_watchlist,
    watchlist_adjust_manifest_summary,
)


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 61000,
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "cost": 255.87}],
        "watchlist": [
            {"code": "603986", "name": "兆易创新"},
            {"code": "002273", "name": "水晶光电"},
        ],
    }


@pytest.fixture
def snapshot(portfolio):
    return {
        "mss_final": 48.0,
        "mss_breakdown": {"fx": 47, "flow": 48, "global": 46, "sentiment": 53},
        "watchlist": [
            {"code": "603986", "name": "兆易创新", "price": 603.17, "change_pct": -2.71},
            {"code": "002273", "name": "水晶光电", "price": 32.04, "change_pct": -6.23},
        ],
        "portfolio": {
            "holdings": [
                {"code": "688008", "name": "澜起科技", "price": 247.15, "change_pct": -2.39},
            ],
        },
    }


@pytest.fixture
def settings():
    s = load_settings()
    s.setdefault("watchlist", {})
    s["watchlist"]["auto_adjust_enabled"] = True
    s["watchlist"]["min_size"] = 0
    return s


def test_enrich_quote_fetch_meta_marks_fallback():
    meta = enrich_quote_fetch_meta(
        {"sources_used": ["eastmoney", "akshare"], "coverage_pct": 100.0, "errors": {}},
        QuoteFetchResult(
            quotes={
                "600000": {"code": "600000", "price": 10.0, "source": "akshare"},
                "600519": {"code": "600519", "price": 20.0, "source": "eastmoney"},
            },
            sources_used=["eastmoney", "akshare"],
        ),
        settings={"quote_fetch": {"sources": ["eastmoney", "xueqiu", "akshare"]}},
    )
    assert meta["primary_source"] == "eastmoney"
    assert meta["fallback_used"] is True
    assert "akshare" in meta["fallback_sources"]
    assert "600000" in meta.get("fallback_codes", [])


def test_portfolio_quote_coverage_merged_holdings_watchlist():
    pf = {
        "holdings": [{"code": "688008", "name": "A", "price": 1.0, "change_pct": 1.0, "source": "eastmoney"}],
        "watchlist": [{"code": "603986", "name": "B"}],
    }
    enriched = {
        "688008": {"price": 1.0, "change_pct": 1.0, "source": "eastmoney"},
        "603986": {},
    }
    cov = portfolio_quote_coverage(pf, enriched, settings={"data_audit": {"min_quote_coverage_pct": 0.8}})
    assert cov["symbol_count"] == 2
    assert cov["quoted_count"] == 1
    assert cov["coverage_pct"] == 50.0
    assert cov["below_threshold"] is True


def test_close_summary_shows_portfolio_quote_warning():
    ctx = CloseCardContext(
        portfolio_summary={
            "daily_pnl": 100.0,
            "daily_pnl_pct": 0.1,
            "portfolio_quote_coverage": {
                "symbol_count": 4,
                "quoted_count": 2,
                "coverage_pct": 50.0,
                "below_threshold": True,
                "threshold_pct": 80.0,
                "missing_codes": ["603986"],
            },
        },
        symbol_rows=[],
    )
    md = render_close_summary_markdown(ctx)
    assert "行情覆盖" in md
    assert "50.0%" in md
    assert "⚠️" in md


def test_watchlist_adjust_manifest_summary_always_present():
    disabled = watchlist_adjust_manifest_summary(None, enabled=False)
    assert disabled["status"] == "disabled"
    assert disabled["change_count"] == 0

    unchanged = watchlist_adjust_manifest_summary(
        WatchlistAdjustResult(applied=False, portfolio={}, message="观察池无变更"),
        enabled=True,
    )
    assert unchanged["status"] == "unchanged"
    assert unchanged["message"] == "观察池无变更"


def test_min_size_floor_blocks_hot_refresh_drain(portfolio, snapshot, settings):
    settings["watchlist"]["min_size"] = 5
    settings["watchlist"]["hot_topic_adjust_enabled"] = True
    settings["watchlist"]["hot_topic_fetch_if_missing"] = False
    settings["watchlist"]["candidates"] = [
        {"code": "000725", "name": "京东方A", "keywords": ["京东方"]},
    ]
    portfolio["watchlist"] = [
        {"code": "603986", "name": "兆易创新"},
        {"code": "002273", "name": "水晶光电"},
    ]
    snapshot["hot_topics_matched"] = [{"title": "京东方面板"}]
    snapshot["watchlist"] = [
        {"code": "603986", "name": "兆易创新", "change_pct": -1.0},
        {"code": "002273", "name": "水晶光电", "change_pct": 1.0},
    ]
    result = adjust_watchlist(portfolio, snapshot, settings, "close")
    assert len(result.portfolio["watchlist"]) >= 2
    assert not any(c.action == "remove" and "热点刷新" in c.reason for c in result.changes)
