# -*- coding: utf-8
"""Tests for session verdict guards (pullback downgrade + watchlist alerts)."""

from agent_reach.daily_run.session_verdict_guards import (
    apply_session_pullback_verdict_downgrade,
    collect_watchlist_drawdown_alerts,
    format_volume_ratio_note,
    morning_buy_verdict,
    render_watchlist_drawdown_markdown,
)
from agent_reach.daily_run.verdict import compute_verdict


def test_format_volume_ratio_note_up_vs_down():
    assert "筹码稳定" in format_volume_ratio_note(0.8, 1.5, 1.0)
    assert "流动性" in format_volume_ratio_note(0.8, -1.0, 1.0)


def test_morning_buy_verdict_detects_s1():
    scans = [{"scan_id": "S1", "verdict": "可做", "source": "morning", "mss_final": 51}]
    verdict, sid = morning_buy_verdict(scans, settings={})
    assert verdict == "可做"
    assert sid == "S1"


def test_pullback_downgrade_可做_to_观察():
    settings = {
        "verdict_labels": {"buy": "可做", "watch": "观察", "avoid": "回避"},
        "thresholds": {"macro_veto": 35, "aggressive_entry": 50, "min_volume_ratio": 1.0},
        "intraday": {
            "session_verdict_guards": {
                "enabled": True,
                "min_scan_num": 4,
                "price_pullback_pct": 2.0,
                "mss_pullback_pts": 2.0,
            }
        },
    }
    session_scans = [
        {"scan_id": "S1", "verdict": "可做", "source": "morning", "mss_final": 52, "price": 110.0, "code": "601138"},
        {"scan_id": "S2", "verdict": "可做", "mss_final": 51, "price": 109.0, "code": "601138"},
        {"scan_id": "S3", "verdict": "可做", "mss_final": 51, "price": 108.0, "code": "601138"},
    ]
    snapshot = {
        "code": "601138",
        "name": "工业富联",
        "price": 106.0,
        "change_pct": -2.7,
        "ma20": 100.0,
        "position_20d": 0.5,
        "volume_ratio": 1.1,
        "mss_final": 51.0,
        "mss_breakdown": {"fx": 50, "flow": 50, "global": 50, "sentiment": 50},
        "audit_passed": True,
        "structured_review_complete": True,
    }
    verdict = compute_verdict(snapshot, settings)
    evaluation = {
        "report": {
            **verdict.to_dict(),
            "code": "601138",
            "name": "工业富联",
            "mss_final": 51.0,
            "reasoning": verdict.reasoning,
            "downgrade_reasons": list(verdict.downgrade_reasons),
        },
        "verdict": verdict,
    }
    meta = apply_session_pullback_verdict_downgrade(
        evaluation,
        snapshot,
        session_scans,
        settings,
        pending_scan_num=4,
    )
    assert meta is not None
    assert evaluation["report"]["verdict"] == "观察"
    assert evaluation["report"].get("session_pullback_downgrade")


def test_watchlist_drawdown_alerts_red_and_yellow():
    portfolio = {
        "watchlist": [
            {"code": "002415", "name": "海康威视", "change_pct": -3.5, "day_low": 28.0, "prev_close": 30.0},
            {"code": "002583", "name": "海能达", "change_pct": -1.0, "day_low": 9.8, "prev_close": 10.0},
        ]
    }
    alerts = collect_watchlist_drawdown_alerts(
        portfolio,
        settings={"intraday": {"watchlist_drawdown": {"yellow_pct": -3.0, "red_pct": -5.0}}},
    )
    assert any(a["code"] == "002415" and a["severity"] == "red" for a in alerts)
    md = render_watchlist_drawdown_markdown(portfolio, settings={"intraday": {"watchlist_drawdown": {}}})
    assert "观察池跌幅哨兵" in md
    assert "海康威视" in md


def test_compute_verdict_low_volume_up_not_downgraded_to_watch():
    settings = {
        "verdict_labels": {"buy": "可做", "watch": "观察", "avoid": "回避"},
        "thresholds": {"macro_veto": 35, "aggressive_entry": 50, "min_volume_ratio": 1.0},
    }
    snapshot = {
        "price": 10.0,
        "ma20": 9.5,
        "position_20d": 0.4,
        "volume_ratio": 0.8,
        "change_pct": 1.2,
        "mss_final": 60.0,
        "audit_passed": True,
        "structured_review_complete": True,
    }
    result = compute_verdict(snapshot, settings)
    assert any("筹码稳定" in r for r in result.downgrade_reasons)
    assert not any("量比" in r and "<" in r for r in result.downgrade_reasons)
