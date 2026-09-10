# -*- coding: utf-8
"""Tests for systemic risk detectors and northbound labeling."""

from agent_reach.daily_run.eastmoney_market import fetch_north_flow
from agent_reach.daily_run.systemic_risk import (
    collect_systemic_risk_findings,
    current_from_portfolio_summary,
    detect_emotion_cooling,
    format_northbound_display,
    is_tech_cluster_sector,
    systemic_buy_block_reason,
    systemic_risk_narrative_context,
    tech_concentration_snapshot,
    watchlist_diversify_score_adjustment,
)


def test_northbound_disclosure_limited_label():
    label = format_northbound_display({"disclosure_limited": True, "net_yi": 0.0})
    assert "未披露" in label


def test_fetch_north_flow_uses_kamt_get():
    result = fetch_north_flow()
    assert result.get("available") is True
    assert "disclosure_limited" in result
    assert result.get("source") == "eastmoney_kamt"


def test_tech_concentration_detects_cluster():
    snap = tech_concentration_snapshot(
        {
            "holdings": [
                {"code": "688981", "shares": 100, "sector": "半导体"},
                {"code": "603986", "shares": 100, "sector": "存储"},
            ],
            "watchlist": [
                {"code": "000725", "sector": "面板"},
                {"code": "300308", "sector": "光通信"},
            ],
        }
    )
    assert snap["ratio"] == 1.0
    assert is_tech_cluster_sector("半导体")


def test_watchlist_diversify_boosts_non_tech():
    boost = watchlist_diversify_score_adjustment(
        {"sector": "医药"},
        portfolio={
            "holdings": [{"code": "688981", "shares": 1, "sector": "半导体"}],
            "watchlist": [{"code": "603986", "sector": "存储"}],
        },
        settings={"systemic_risk": {"tech_cluster_ratio_warn": 0.5}},
    )
    assert boost > 0


def test_emotion_cooling_from_market_review():
    cooling = detect_emotion_cooling(
        {
            "emotion": {"rating": "弱"},
            "comparison": {"vs_yesterday": {"limit_up_delta": -25, "limit_down_delta": 7}},
            "sector_analysis": {
                "mainline_type": "多题材轮动",
                "reasoning": "题材分散：最强 农产品加工 仅 4 家涨停",
            },
            "north": {"disclosure_limited": True},
        }
    )
    assert cooling is not None
    assert any("涨停" in s for s in cooling["signals"])


def test_systemic_buy_block_on_cooling_and_concentration():
    reason = systemic_buy_block_reason(
        {"systemic_risk": {"tech_cluster_ratio_block_buy": 0.5, "block_tech_buy_on_cooling": True}},
        code="688981",
        snapshot={
            "portfolio": {
                "holdings": [{"code": "688981", "shares": 100, "sector": "半导体"}],
                "watchlist": [{"code": "603986", "sector": "存储"}],
            },
            "symbols": [{"code": "688981", "sector": "半导体"}],
            "market_review": {
                "comparison": {"vs_yesterday": {"limit_up_delta": -20, "limit_down_delta": 5}},
                "sector_analysis": {"mainline_type": "多题材轮动", "reasoning": "题材分散"},
            },
        },
    )
    assert reason is not None
    assert "系统性风险" in reason


def test_collect_systemic_risk_findings():
    findings = collect_systemic_risk_findings(
        current={
            "portfolio": {
                "daily_pnl_pct": -0.04,
                "holdings": [
                    {"code": "688981", "shares": 100, "sector": "半导体", "name": "中芯"},
                    {"code": "603986", "shares": 100, "sector": "存储", "name": "兆易"},
                ],
            },
            "watchlist": [
                {"code": "000725", "sector": "面板", "name": "京东方"},
            ],
            "market_review": {
                "date": "2026-09-09",
                "comparison": {"vs_yesterday": {"limit_up_delta": -25, "limit_down_delta": 7}},
                "sector_analysis": {
                    "mainline_type": "多题材轮动",
                    "reasoning": "题材分散：最强 农产品加工 仅 4 家涨停",
                },
                "north": {"disclosure_limited": True, "net_yi": 0.0},
                "emotion": {"rating": "弱"},
                "indices": {"sh000300": {"change_pct": 0.30}},
            },
        },
        settings={"systemic_risk": {"tech_cluster_ratio_warn": 0.7}},
    )
    titles = {f["title"] for f in findings}
    assert "市场情绪降温" in titles
    assert "科技链高度集中" in titles


def test_systemic_risk_narrative_context_from_portfolio_summary():
    ctx = systemic_risk_narrative_context(
        portfolio_summary={
            "holdings": [{"code": "688981", "shares": 100, "sector": "半导体"}],
            "watchlist": [{"code": "603986", "sector": "存储"}],
        },
        settings={"systemic_risk": {"tech_cluster_ratio_warn": 0.5}},
    )
    assert ctx
    assert ctx[0]["title"] == "科技链高度集中"
    assert "detail" in ctx[0]


def test_current_from_portfolio_summary_shape():
    current = current_from_portfolio_summary({"holdings": [{"code": "688981"}], "daily_pnl_pct": -0.2})
    assert current["portfolio"]["holdings"][0]["code"] == "688981"
    assert current["daily_pnl_pct"] == -0.2
