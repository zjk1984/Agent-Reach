# -*- coding: utf-8 -*-
"""Phase-2 tests: verify, backtest, akshare adapter (mocked)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from agent_reach.daily_run.akshare_adapter import enrich_snapshot, normalize_symbol
from agent_reach.daily_run.backtest import run_mss_backtest
from agent_reach.daily_run.verify import render_verify_markdown, verify_snapshots


class TestNormalizeSymbol:
    def test_sh_code(self):
        assert normalize_symbol("688008") == ("688008", "sh")

    def test_sz_code(self):
        assert normalize_symbol("002273") == ("002273", "sz")


class TestVerify:
    @pytest.fixture
    def baseline(self):
        return {
            "code": "688008",
            "name": "澜起科技",
            "price": 253.20,
            "mss_final": 65,
            "verdict": "可做",
            "mss_range": [45, 58],
            "macro_summary": "预测 MSS [45, 58]",
        }

    @pytest.fixture
    def current(self):
        return {
            "code": "688008",
            "name": "澜起科技",
            "price": 255.87,
            "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
        }

    def test_verify_mss_prediction_miss(self, baseline, current):
        result = verify_snapshots(baseline, current)
        assert result.mss_within_prediction is False
        assert result.mss_current == 42.5
        assert any("低于预测" in d for d in result.deviations)

    def test_verify_markdown(self, baseline, current):
        result = verify_snapshots(baseline, current)
        md = render_verify_markdown(result)
        assert "验证摘要" in md
        assert "688008" in md or "澜起" in md


class TestBacktest:
    def test_run_mss_backtest(self):
        history = [
            {"date": "2026-07-01", "mss": 55, "price": 100, "return": 0.01},
            {"date": "2026-07-02", "mss": 52, "price": 101, "return": 0.005},
            {"date": "2026-07-03", "mss": 48, "price": 100.5, "return": -0.005},
            {"date": "2026-07-04", "mss": 38, "price": 98, "return": -0.02},
        ]
        result = run_mss_backtest(history)
        assert result.metrics.trade_count >= 1
        assert len(result.equity_curve) > 1

    def test_example_history_file(self):
        from pathlib import Path

        history = json.loads(
            Path("config/daily_run_history.example.json").read_text(encoding="utf-8")
        )
        result = run_mss_backtest(history)
        assert "策略收益" in result.summary()


class TestAKShareAdapter:
    @patch("agent_reach.daily_run.akshare_adapter._import_akshare")
    def test_enrich_snapshot(self, mock_import):
        ak = MagicMock()
        mock_import.return_value = ak
        ak.stock_zh_a_spot_em.return_value = pd.DataFrame(
            [{"代码": "688008", "名称": "澜起科技", "最新价": 255.87, "涨跌幅": 1.05, "量比": 1.1, "成交额": 1e9}]
        )
        ak.stock_zh_a_hist.return_value = pd.DataFrame(
            {
                "收盘": [240 + i for i in range(25)],
                "成交量": [1000 + i * 10 for i in range(25)],
            }
        )
        merged = enrich_snapshot({}, "688008")
        assert merged["code"] == "688008"
        assert merged["price"] == 255.87
        assert merged["structured_review_complete"] is True
        assert "quote" in merged["sources"]
