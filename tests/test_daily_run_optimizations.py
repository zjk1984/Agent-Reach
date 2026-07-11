# -*- coding: utf-8
"""Tests for Phase A-E optimizations."""

from unittest.mock import patch

import pytest

from agent_reach.daily_run.curve_analysis import analyze_intraday_curve, render_curve_markdown
from agent_reach.daily_run.mss_forecast import forecast_mss_range
from agent_reach.daily_run.schedule import INTRADAY_SCAN_TIMES, default_entries
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.verdict import compute_verdict, fuse_verdict_with_team


class TestMssForecast:
    def test_forecast_range(self):
        snap = {"mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50}}
        rng, meta = forecast_mss_range(snap, load_settings(), simulations=50)
        assert len(rng) == 2
        assert rng[0] <= rng[1]
        assert meta["method"] == "monte_carlo_lite"


class TestCurveAnalysis:
    def test_analyze_intraday_curve(self):
        analysis = analyze_intraday_curve([42, 44, 46, 45], predicted_range=(40, 52))
        assert analysis["points"] == 4
        md = render_curve_markdown(analysis)
        assert "盘中 MSS 曲线" in md


class TestVerdictFusion:
    def test_fuse_team_consensus_downgrade(self):
        settings = load_settings()
        snap = {
            "code": "688008",
            "price": 100,
            "ma20": 95,
            "position_20d": 0.5,
            "volume_ratio": 1.2,
            "mss_breakdown": {"fx": 55, "flow": 55, "global": 55, "sentiment": 55},
            "sources": {"quote": {"summary": "q"}, "flow": {"summary": "f"}, "sentiment": {"summary": "s"}},
            "team_consensus_label": "观察",
            "team_review": {"consensus_score": 45, "consensus_label": "观察"},
        }
        base = compute_verdict(snap, settings)
        fused = fuse_verdict_with_team(base, snap, settings)
        assert fused.verdict == "观察"

    def test_buffett_block(self):
        settings = load_settings()
        snap = {
            "code": "688008",
            "price": 100,
            "ma20": 95,
            "position_20d": 0.5,
            "volume_ratio": 1.2,
            "peg": 2.5,
            "mss_breakdown": {"fx": 55, "flow": 55, "global": 55, "sentiment": 55},
            "sources": {"quote": {"summary": "q"}, "flow": {"summary": "f"}, "sentiment": {"summary": "s"}},
        }
        base = compute_verdict(snap, settings)
        fused = fuse_verdict_with_team(base, snap, settings)
        assert fused.blocked is True


class TestScheduleEntries:
    def test_eleven_intraday_scan_slots(self):
        assert len(INTRADAY_SCAN_TIMES) == 11

    def test_default_entries_count(self):
        assert len(default_entries()) == 15  # morning + 11 scans + close + weekly + forecast


class TestMacroCollector:
    @patch("agent_reach.daily_run.macro_collector._fetch_index_change", return_value=0.5)
    @patch("agent_reach.daily_run.macro_collector._fetch_northbound_flow", return_value=12.0)
    @patch("agent_reach.daily_run.macro_collector._fetch_xueqiu_sentiment", return_value=("雪球热点：存储", []))
    def test_collect_macro_context(self, *_mocks):
        from agent_reach.daily_run.macro_collector import collect_macro_context

        pf = {"mss_breakdown": {"fx": 50, "flow": 50, "global": 50, "sentiment": 50}}
        ctx = collect_macro_context(pf, settings=load_settings())
        assert "flow" in ctx["sources"]
        assert ctx["mss_breakdown"]["flow"] > 50
