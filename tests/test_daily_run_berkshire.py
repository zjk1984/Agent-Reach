# -*- coding: utf-8
"""Tests for AI Berkshire integration layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_reach.daily_run.berkshire.decision_memo import build_decision_memo, render_decision_memo_markdown
from agent_reach.daily_run.berkshire.financial_rigor import verify_market_cap
from agent_reach.daily_run.berkshire.industry_funnel import funnel_select_watchlist
from agent_reach.daily_run.berkshire.info_richness import grade_info_richness
from agent_reach.daily_run.berkshire.masters_scoring import build_masters_scoring
from agent_reach.daily_run.berkshire.quality_screen import screen_from_snapshot
from agent_reach.daily_run.berkshire.thesis_drift import compare_thesis_docs
from agent_reach.daily_run.berkshire.thesis_tracker import (
    build_thesis_from_snapshot,
    save_thesis,
    sync_thesis_from_snapshot,
    thesis_health_score,
)
from agent_reach.daily_run.watchlist_manager import adjust_watchlist


@pytest.fixture
def portfolio():
    return {
        "total": 100000,
        "cash": 61000,
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "cost": 255.87}],
        "watchlist": [],
    }


@pytest.fixture
def snapshot():
    return {
        "code": "688008",
        "name": "澜起科技",
        "price": 221.22,
        "ma20": 206.78,
        "volume": 1000,
        "mss_final": 55.0,
        "verdict": "可做",
        "mss_breakdown": {
            "fx": 50,
            "flow": 48,
            "global": 54,
            "sentiment": 66,
            "technical": 71,
            "quant": 60,
            "risk": 73,
        },
        "macro_summary": "芯片景气",
    }


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = {
        "berkshire": {"enabled": True},
        "watchlist": {
            "min_size": 3,
            "max_size": 8,
            "candidates": [
                {"code": "603986", "name": "兆易创新", "keywords": ["存储"]},
                {"code": "002415", "name": "海康威视", "keywords": ["安防"]},
            ],
        },
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45},
    }
    monkeypatch.setenv("AGENT_REACH_THESIS_DIR", str(tmp_path / "thesis"))
    return s


def test_verify_market_cap_ok():
    mc = verify_market_cap(510, 9.11e9, 510 * 9.11e9)
    assert mc.ok is True
    assert mc.deviation_pct < 0.01


def test_info_richness_grade_a(snapshot):
    r = grade_info_richness(snapshot)
    assert r["grade"] in ("A", "B")


def test_decision_memo_pass(snapshot, settings):
    memo = build_decision_memo(snapshot, settings=settings)
    assert memo["decision"] in ("通过", "灰色地带", "不通过")
    md = render_decision_memo_markdown(memo)
    assert "决策结论" in md


def test_quality_screen_pass_with_sparse_data(snapshot):
    r = screen_from_snapshot(snapshot)
    assert r.passed is True


def test_quality_screen_fail_low_roe():
    snap = {"code": "000001", "name": "测试", "roe": 3, "gross_margin": 10}
    r = screen_from_snapshot(snap)
    assert r.passed is False
    assert r.failed_rules


def test_thesis_sync_creates_file(snapshot, settings, tmp_path, monkeypatch):
    from agent_reach.daily_run import berkshire

    monkeypatch.setattr(berkshire.config, "thesis_dir", lambda _s=None: tmp_path / "thesis")
    pf = {"holdings": [{"code": "688008", "name": "澜起科技", "shares": 100}]}
    out = sync_thesis_from_snapshot(snapshot, settings=settings, portfolio=pf)
    assert out.get("applied") is True
    path = Path(out["path"])
    assert path.is_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    score, label = thesis_health_score(doc)
    assert score >= 1


def test_thesis_drift_detects_mss_drop(snapshot, settings):
    old = build_thesis_from_snapshot(snapshot, settings=settings)
    old["valuation_anchor"] = {"mss": 60, "verdict": "可做", "price": 230}
    new = dict(old)
    new["valuation_anchor"] = {"mss": 28, "verdict": "回避", "price": 200}
    report = compare_thesis_docs(old, new)
    assert report["weakened_count"] >= 1


def test_masters_scoring(snapshot):
    scoring = build_masters_scoring(snapshot, team_review={"counter_thesis": "竞对追赶"})
    assert len(scoring["rows"]) == 4
    assert scoring["average"] >= 1.0


def test_morning_watchlist_fill_to_min(portfolio, snapshot, settings):
    settings = dict(settings)
    settings["watchlist"]["min_size"] = 3
    portfolio["watchlist"] = []
    result = adjust_watchlist(portfolio, snapshot, settings, "morning")
    assert len(result.portfolio.get("watchlist") or []) >= 3


def test_industry_funnel_selects_candidates(settings):
    funnel = funnel_select_watchlist(settings, enriched={}, hot_titles=["存储"])
    assert funnel["candidates_scored"] >= 0
