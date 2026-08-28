# -*- coding: utf-8
"""Tests for harness-evolved MarketEmotion policy."""

from agent_reach.daily_run.market_breadth_collector import analyze_emotion
from agent_reach.daily_run.market_emotion_policy import (
    format_market_emotion_policy_line,
    market_emotion_policy_base,
    market_emotion_policy_default,
    parse_market_emotion_policy_line,
    rating_position_from_score,
    resolve_harness_market_emotion_policy,
)


def test_market_emotion_policy_base_defaults():
    base = market_emotion_policy_base({})
    assert base["ratio_strong"] == 2.0
    assert base["score_strong_min"] == 4.0


def test_rating_position_from_score_uses_policy():
    assert rating_position_from_score(4, settings={}) == ("强", "7-8成")
    assert rating_position_from_score(1, settings={}) == ("中", "5成")
    assert rating_position_from_score(0, settings={}) == ("弱", "2-3成")
    settings = {"market_review": {"score_neutral_min": 2.0, "score_strong_min": 5.0}}
    assert rating_position_from_score(2, settings=settings) == ("中", "5成")
    assert rating_position_from_score(1, settings=settings) == ("弱", "2-3成")


def test_analyze_emotion_respects_higher_limit_up_hot():
    stocks = [{"change_pct": 10.0} for _ in range(70)]
    stocks += [{"change_pct": 1.0} for _ in range(30)]
    default_em = analyze_emotion(stocks, {"net_yi": 0})
    strict_em = analyze_emotion(
        stocks,
        {"net_yi": 0},
        settings={"market_review": {"limit_up_hot": 100.0, "limit_up_normal": 60.0}},
    )
    assert default_em.score >= strict_em.score


def test_parse_market_emotion_policy_line():
    line = format_market_emotion_policy_line(
        {
            "ratio_strong": 2.2,
            "ratio_neutral": 1.1,
            "limit_up_hot": 85,
            "score_strong_min": 5,
            "score_neutral_min": 2,
        }
    )
    parsed = parse_market_emotion_policy_line(line)
    assert parsed is not None
    assert parsed["ratio_strong"] == 2.2
    assert parsed["score_neutral_min"] == 2.0


def test_resolve_harness_market_emotion_policy_tightens_on_insufficient_phrase(monkeypatch):
    settings = {"market_review": {"emotion_mode": "harness"}, "harness": {"enabled": True}}

    def _fake_overlay(state, phrase, *, settings):
        return phrase in {"市场宽度不足", "暂无仓位建议"}

    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy._overlay_has_phrase",
        _fake_overlay,
    )
    resolved = resolve_harness_market_emotion_policy(object(), settings=settings)
    assert resolved["score_neutral_min"] >= 2.0
