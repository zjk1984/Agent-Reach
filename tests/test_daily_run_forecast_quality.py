# -*- coding: utf-8
"""Tests for Sunday forecast quality (evidence, width, confidence, cross-check)."""

from agent_reach.daily_run.forecast_quality import (
    audit_forecast_cross_check,
    clamp_pct_band,
    confidence_tier,
    enrich_market_prediction,
    enrich_symbol_prediction,
    format_evidence_suffix,
    interval_width_pct,
    position_hint_for_confidence,
)


def test_clamp_market_width():
    lo, hi, width = clamp_pct_band(0.0, 5.0, mid=2.5, min_width=2.0, max_width=4.0)
    assert width <= 4.0
    assert width >= 2.0


def test_clamp_stock_width():
    lo, hi, width = clamp_pct_band(-10.0, 10.0, mid=0.0, min_width=8.0, max_width=15.0)
    assert width <= 15.0
    assert width >= 8.0


def test_enrich_market_has_evidence_and_confidence():
    pred = enrich_market_prediction(
        {
            "index_name": "沪深300",
            "change_pct_low": 0.5,
            "change_pct_high": 1.5,
            "change_pct_mid": 1.0,
        },
        snapshot={"mss_final": 68, "mss_breakdown": {"flow": 62}},
        mss_daily={"2026-08-25": {"median": 52}, "2026-08-29": {"median": 54}},
        calibration={"hit_rate": 0.75},
    )
    assert "依据：" in pred["text"]
    assert pred.get("confidence_pct") is not None
    assert pred.get("interval_width_pct") is not None
    assert pred["interval_width_pct"] <= 4.0


def test_enrich_symbol_low_confidence_flag():
    pred = enrich_symbol_prediction(
        {
            "code": "300308",
            "name": "中际旭创",
            "base_price": 118.0,
            "change_pct_low": -20.0,
            "change_pct_high": 20.0,
            "change_pct_mid": 0.0,
            "price_low": 94.0,
            "price_high": 142.0,
            "price_mid": 118.0,
        },
        sym={"days": {"2026-08-25": {"confidence": 0.4}}},
        enriched={"price": 118.0, "ma20": 110.0, "mss_final": 52},
    )
    assert pred.get("confidence_pct", 100) < 60 or "低置信度" in pred["text"] or pred.get("confidence_tier") == "低"
    assert "依据：" in pred["text"]
    assert pred.get("interval_width_pct") is not None


def test_cross_check_detects_price_mismatch():
    structured = {
        "symbols": [
            {"code": "300308", "name": "中际旭创", "base_price": 120.0},
        ]
    }
    reference = {
        "cutoff_label": "2026-08-29 收盘",
        "holdings": {
            "300308": {
                "name": "中际旭创",
                "close_price": 118.0,
                "source": "close_baseline",
                "as_of": "2026-08-29",
            }
        },
    }
    audit = audit_forecast_cross_check(structured, reference, tolerance_pct=0.5)
    assert audit["rows"]
    assert audit["ok"] is False


def test_position_hint_by_confidence():
    assert position_hint_for_confidence(85) == "正常仓位"
    assert position_hint_for_confidence(70) == "轻仓"
    assert position_hint_for_confidence(50) == "观望或极小仓位"


def test_format_evidence_suffix():
    text = format_evidence_suffix(["①技术面站稳20日均线", "②MSS模型评分68/100（偏多）"])
    assert text.startswith("依据：")
    assert "①" in text


def test_confidence_tier():
    assert confidence_tier(85) == "高"
    assert confidence_tier(70) == "中"
    assert confidence_tier(50) == "低"
