# -*- coding: utf-8
"""Tests for emotion grade → MSS fusion."""

from agent_reach.daily_run.emotion_mss_fusion import (
    apply_emotion_to_mss_breakdown,
    emotion_mss_deltas,
    format_emotion_fusion_line,
)


def test_emotion_mss_deltas_strong():
    deltas = emotion_mss_deltas({"score": 5, "rating": "强"}, settings={})
    assert deltas["global"] > 0
    assert deltas["sentiment"] > 0


def test_emotion_mss_deltas_weak():
    deltas = emotion_mss_deltas({"score": -1, "rating": "弱"}, settings={})
    assert deltas["global"] < 0
    assert deltas["sentiment"] < 0


def test_apply_emotion_to_mss_breakdown():
    out = apply_emotion_to_mss_breakdown(
        {"global": 50.0, "sentiment": 48.0, "flow": 52.0, "fx": 49.0},
        {"score": 5, "rating": "强", "position": "7-8成", "up_count": 3000, "down_count": 1000},
        settings={"market_review": {"emotion_mss_fusion_enabled": True}},
    )
    assert out["global"] > 50.0
    assert out["sentiment"] > 48.0
    assert out["_emotion_fusion_ref"]["rating"] == "强"
    assert "情绪融合" in format_emotion_fusion_line(out)


def test_apply_emotion_skipped_when_insufficient_data():
    out = apply_emotion_to_mss_breakdown(
        {"global": 50.0, "sentiment": 48.0},
        {"score": 3, "rating": "中", "position": "5成", "insufficient_data": True},
        settings={"market_review": {"emotion_mss_fusion_enabled": True}},
    )
    assert out["global"] == 50.0
    assert out["sentiment"] == 48.0
    assert "_emotion_fusion_ref" not in out
