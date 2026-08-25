# -*- coding: utf-8
"""Unit tests for board price-limit / suspension tradability gates."""

from agent_reach.daily_run.tradability import (
    board_limit_pct,
    is_suspended,
    price_limit_state,
    tradability_block_reason,
)


class TestBoardLimitPct:
    def test_main_board_default(self):
        assert board_limit_pct("600584") == 10.0
        assert board_limit_pct("002273") == 10.0

    def test_main_board_st(self):
        assert board_limit_pct("600001", "*ST某某") == 5.0
        assert board_limit_pct("600001", "ST某某") == 5.0

    def test_chinext(self):
        assert board_limit_pct("300750") == 20.0
        assert board_limit_pct("301029") == 20.0

    def test_star_market(self):
        assert board_limit_pct("688008") == 20.0

    def test_beijing_exchange(self):
        assert board_limit_pct("830799") == 30.0
        assert board_limit_pct("430047") == 30.0

    def test_exchange_prefix_stripped(self):
        assert board_limit_pct("SH688008") == 20.0
        assert board_limit_pct("SZ300750") == 20.0


class TestPriceLimitState:
    def test_limit_up(self):
        assert price_limit_state(9.98, 10.0) == "limit_up"
        assert price_limit_state(10.0, 10.0) == "limit_up"

    def test_limit_down(self):
        assert price_limit_state(-9.98, 10.0) == "limit_down"
        assert price_limit_state(-10.0, 10.0) == "limit_down"

    def test_normal(self):
        assert price_limit_state(5.0, 10.0) is None
        assert price_limit_state(-5.0, 10.0) is None

    def test_none_input(self):
        assert price_limit_state(None, 10.0) is None


class TestIsSuspended:
    def test_zero_volume(self):
        assert is_suspended({"volume": 0}) is True

    def test_zero_turnover(self):
        assert is_suspended({"turnover": 0.0}) is True

    def test_nonzero_volume(self):
        assert is_suspended({"volume": 1000, "turnover": 500000}) is False

    def test_missing_fields_fail_open(self):
        assert is_suspended({}) is False
        assert is_suspended({"price": 10.0}) is False


class TestTradabilityBlockReason:
    def test_buy_blocked_at_limit_up(self):
        row = {"code": "000725", "name": "京东方A", "change_pct": 9.96}
        reason = tradability_block_reason(row, side="buy")
        assert reason is not None
        assert "涨停" in reason

    def test_sell_blocked_at_limit_down(self):
        row = {"code": "002273", "name": "水晶光电", "change_pct": -9.96}
        reason = tradability_block_reason(row, side="sell")
        assert reason is not None
        assert "跌停" in reason

    def test_sell_allowed_at_limit_up(self):
        """Selling into strength (limit-up) is not blocked — only buying is risky."""
        row = {"code": "000725", "name": "京东方A", "change_pct": 9.96}
        assert tradability_block_reason(row, side="sell") is None

    def test_buy_allowed_at_limit_down(self):
        """Buying at limit-down is a strategy choice, not a mechanical block."""
        row = {"code": "002273", "name": "水晶光电", "change_pct": -9.96}
        assert tradability_block_reason(row, side="buy") is None

    def test_star_board_uses_20pct_limit(self):
        row = {"code": "688008", "name": "澜起科技", "change_pct": 15.0}
        assert tradability_block_reason(row, side="buy") is None
        row["change_pct"] = 19.9
        reason = tradability_block_reason(row, side="buy")
        assert reason is not None and "涨停" in reason

    def test_suspended_blocks_both_sides(self):
        row = {"code": "600584", "name": "长电科技", "volume": 0, "change_pct": 0.0}
        assert tradability_block_reason(row, side="buy") is not None
        assert tradability_block_reason(row, side="sell") is not None
        assert "停牌" in tradability_block_reason(row, side="buy")

    def test_no_block_reason_when_normal(self):
        row = {"code": "600584", "name": "长电科技", "change_pct": 1.2, "volume": 12345}
        assert tradability_block_reason(row, side="buy") is None
        assert tradability_block_reason(row, side="sell") is None

    def test_missing_change_pct_fails_open(self):
        row = {"code": "600584", "name": "长电科技"}
        assert tradability_block_reason(row, side="buy") is None
        assert tradability_block_reason(row, side="sell") is None
