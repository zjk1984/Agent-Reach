# -*- coding: utf-8
"""Tests for multi-source quote fetch helpers."""

from unittest.mock import MagicMock, patch

from agent_reach.daily_run.quote_fetch import (
    _fetch_xueqiu,
    _merge_valuation_fields,
    _parse_eastmoney_change_pct,
    _parse_eastmoney_market_cap,
    _parse_eastmoney_nonneg,
    _parse_eastmoney_pe_ttm,
    _parse_eastmoney_turnover,
    _parse_eastmoney_valuation,
    normalize_code,
)


class TestEastmoneyChangePct:
    def test_f170_scaled_by_100(self):
        data = {"f43": 581, "f60": 586, "f169": -5, "f170": -85}
        assert _parse_eastmoney_change_pct(data) == -0.85

    def test_fallback_from_price_and_prev_close(self):
        data = {"f43": 21191, "f60": 21022}
        assert _parse_eastmoney_change_pct(data) == 0.8

    def test_zero_change(self):
        data = {"f170": 0, "f43": 1000, "f60": 1000}
        assert _parse_eastmoney_change_pct(data) == 0.0


class TestNormalizeCode:
    def test_pad_digits(self):
        assert normalize_code("725") == "000725"


class TestEastmoneyValuation:
    def test_parse_pe_turnover_market_cap(self):
        data = {
            "f162": 3050,
            "f168": 345,
            "f116": 2260000000000,
        }
        assert _parse_eastmoney_pe_ttm(data) == 30.5
        assert _parse_eastmoney_turnover(data) == 3.45
        assert _parse_eastmoney_market_cap(data) == 2260000000000
        parsed = _parse_eastmoney_valuation(data)
        assert parsed["pe_ttm"] == 30.5
        assert parsed["turnover_rate"] == 3.45
        assert parsed["market_capital"] == 2260000000000

    def test_merge_valuation_fields_backfills_missing(self):
        merged = _merge_valuation_fields(
            {"code": "688008", "price": 58.1, "source": "eastmoney"},
            {"pe_ttm": 35.2, "turnover_rate": 2.1},
        )
        assert merged["pe_ttm"] == 35.2
        assert merged["price"] == 58.1

    def test_merge_valuation_fields_backfills_volume_turnover(self):
        """M4: suspension detection needs volume/turnover gap-filled across sources."""
        merged = _merge_valuation_fields(
            {"code": "600584", "price": 30.0, "source": "eastmoney"},
            {"volume": 0.0, "turnover": 0.0},
        )
        assert merged["volume"] == 0.0
        assert merged["turnover"] == 0.0

    def test_merge_valuation_fields_does_not_overwrite_zero(self):
        """A genuine 0 from the primary source must not be masked by a fallback value."""
        merged = _merge_valuation_fields(
            {"code": "600584", "price": 30.0, "volume": 0.0},
            {"volume": 12345.0},
        )
        assert merged["volume"] == 0.0


class TestEastmoneyNonneg:
    """M4: suspension detection needs 0 volume/turnover preserved, unlike
    _optional_float which treats 0 as invalid/missing for valuation fields."""

    def test_zero_is_preserved(self):
        assert _parse_eastmoney_nonneg(0) == 0.0
        assert _parse_eastmoney_nonneg("0") == 0.0

    def test_positive_value(self):
        assert _parse_eastmoney_nonneg(12345) == 12345.0

    def test_none_and_invalid(self):
        assert _parse_eastmoney_nonneg(None) is None
        assert _parse_eastmoney_nonneg("not-a-number") is None

    def test_negative_rejected(self):
        assert _parse_eastmoney_nonneg(-5) is None


class TestFetchXueqiuVolume:
    def test_volume_and_amount_captured(self):
        mock_channel = MagicMock()
        mock_channel.get_stock_quote.return_value = {
            "current": 30.0,
            "name": "长电科技",
            "percent": 1.2,
            "last_close": 29.6,
            "volume": 0,
            "amount": 0,
        }
        with patch("agent_reach.channels.xueqiu.XueqiuChannel", return_value=mock_channel), patch(
            "agent_reach.channels.xueqiu._ensure_cookies",
        ):
            out = _fetch_xueqiu(["600584"], max_retries=0)
        assert out["600584"]["volume"] == 0.0
        assert out["600584"]["turnover"] == 0.0

    def test_missing_volume_omitted(self):
        mock_channel = MagicMock()
        mock_channel.get_stock_quote.return_value = {
            "current": 30.0,
            "name": "长电科技",
            "percent": 1.2,
            "last_close": 29.6,
        }
        with patch("agent_reach.channels.xueqiu.XueqiuChannel", return_value=mock_channel), patch(
            "agent_reach.channels.xueqiu._ensure_cookies",
        ):
            out = _fetch_xueqiu(["600584"], max_retries=0)
        assert "volume" not in out["600584"]
        assert "turnover" not in out["600584"]
