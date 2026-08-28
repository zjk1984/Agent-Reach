# -*- coding: utf-8
"""Tests for market emotion harness refinement."""

from agent_reach.daily_run.market_emotion_harness import market_review_to_harness_evidence


def test_market_review_insufficient_emits_memory():
    evidence = market_review_to_harness_evidence(
        {
            "emotion": {"insufficient_data": True, "rating": "中", "score": 3, "position": "5成"},
            "warnings": ["eastmoney clist: disconnected"],
        }
    )
    assert evidence["emotion_supported"] is False
    assert any("市场宽度不足" in line for line in evidence["memory"])
    assert "market_emotion_insufficient" in evidence["verification_signals"]


def test_market_review_supported_with_basis():
    evidence = market_review_to_harness_evidence(
        {
            "emotion": {
                "rating": "中",
                "score": 3,
                "position": "5成",
                "up_count": 2600,
                "down_count": 1900,
                "data_basis": "雪球沪深宽度 + 涨跌停池(akshare_limit_pools)",
            },
            "warnings": ["eastmoney clist: disconnected"],
        }
    )
    assert evidence["emotion_supported"] is True
    assert any("依据" in line for line in evidence["memory"])
