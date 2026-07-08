# -*- coding: utf-8
"""Tests for intraday scan/trade workflow and lookback MSS."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agent_reach.daily_run.intraday import (
    IntradayState,
    evaluate_trade,
    record_scan,
    reset_state,
    run_intraday,
)
from agent_reach.daily_run.lookback import compute_lookback_mss, detect_mss_trend
from agent_reach.daily_run.settings import load_settings


@pytest.fixture
def intraday_snapshot():
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "code": "688008",
        "name": "澜起科技",
        "price": 255.87,
        "ma20": 260.0,
        "position_20d": 0.55,
        "volume_ratio": 1.2,
        "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
        "sources": {
            "quote": {"summary": "q"},
            "flow": {"summary": "f"},
            "sentiment": {"summary": "s"},
        },
        "structured_review_complete": True,
        "portfolio": {"cash_ratio": 0.61, "total": 91938},
    }


class TestLookback:
    def test_compute_lookback_mss_three_scans(self):
        settings = load_settings()
        scans = [
            {"scan_id": "S1", "mss_final": 40.0},
            {"scan_id": "S2", "mss_final": 45.0},
            {"scan_id": "S3", "mss_final": 50.0},
        ]
        mss, detail = compute_lookback_mss(scans, settings)
        assert mss == pytest.approx(46.5, abs=0.1)
        assert len(detail) == 3
        assert detail[0]["scan_id"] == "S3"

    def test_compute_lookback_single_scan(self):
        settings = load_settings()
        mss, detail = compute_lookback_mss([{"scan_id": "S1", "mss_final": 42.0}], settings)
        assert mss == 42.0
        assert len(detail) == 1

    def test_detect_trend_rising(self):
        scans = [{"mss_final": 40}, {"mss_final": 45}, {"mss_final": 52}]
        assert detect_mss_trend(scans) == "turning_up"


class TestIntradayWorkflow:
    def test_record_scan(self, intraday_snapshot, tmp_path):
        state_path = tmp_path / "intraday.json"
        reset_state(state_path)
        result = record_scan(
            intraday_snapshot,
            settings=load_settings(),
            state_path=state_path,
        )
        assert result["scan"]["scan_id"] == "S1"
        assert result["lookback_mss"] == result["scan"]["mss_final"]
        state = IntradayState.from_dict(result["state"])
        assert len(state.scans) == 1

    def test_evaluate_trade_hold(self, intraday_snapshot, tmp_path):
        state_path = tmp_path / "intraday.json"
        reset_state(state_path)
        settings = load_settings()
        for _ in range(3):
            record_scan(intraday_snapshot, settings=settings, state_path=state_path)
        result = evaluate_trade(
            intraday_snapshot,
            settings=settings,
            state_path=state_path,
            expected_return_pct=0.005,
        )
        assert result["decision"]["trade_id"] == "T1"
        assert result["decision"]["action"] in ("hold", "buy", "sell", "skip")

    def test_max_scans_limit(self, intraday_snapshot, tmp_path):
        state_path = tmp_path / "intraday.json"
        reset_state(state_path)
        settings = load_settings()
        for _ in range(12):
            record_scan(intraday_snapshot, settings=settings, state_path=state_path)
        with pytest.raises(RuntimeError, match="扫描已达上限"):
            record_scan(intraday_snapshot, settings=settings, state_path=state_path)

    @patch("agent_reach.daily_run.intraday.send_card", create=True)
    def test_run_intraday_scan_and_trade(self, mock_send, intraday_snapshot, tmp_path):
        state_path = tmp_path / "intraday.json"
        reset_state(state_path)
        with patch("agent_reach.daily_run.intraday.send_card") as mock_card:
            mock_card.return_value = {"code": 0, "data": {}}
            # Need 3 scans before trade makes sense; run_intraday does 1 scan + trade
            # Pre-seed 2 scans
            settings = load_settings()
            for _ in range(2):
                record_scan(intraday_snapshot, settings=settings, state_path=state_path)
            result = run_intraday(
                intraday_snapshot,
                settings=settings,
                push=False,
                trade=True,
                state_path=state_path,
            )
        assert "scan" in result["steps"]
        assert "trade" in result["steps"]
        assert "push" not in result["steps"]
