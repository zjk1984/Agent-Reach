# -*- coding: utf-8
"""Unit tests for ops quote probe (mocked network)."""

from __future__ import annotations

import os
from unittest.mock import patch

from agent_reach.daily_run import ops_quote_probe as qp
from agent_reach.daily_run.quote_fetch import QuoteFetchResult

os.environ["OPS_QUOTE_PROBE_SKIP_MANIFEST"] = "1"


def test_select_probe_codes_prioritizes_holdings_and_caps():
    portfolio = {
        "holdings": [{"code": "600519", "shares": 100}, {"code": "000001", "shares": 0}],
        "watchlist": [{"code": "002583"}, {"code": "300750"}],
        "primary_code": "601138",
    }
    settings = {"ops": {"quote_probe": {"max_codes": 2}}}
    codes = qp.select_probe_codes(portfolio, settings)
    assert codes == ["600519", "002583"]


def test_classify_quote_missing_and_stale():
    fetch = QuoteFetchResult(
        quotes={"600519": {"price": 10.0, "change_pct": 0.5}},
        errors={"000001": "timeout"},
    )
    assert qp._classify_quote("000001", fetch) == "missing"
    assert qp._classify_quote("600519", fetch) == "ok"
    fetch2 = QuoteFetchResult(
        quotes={
            "002583": {
                "price": 8.0,
                "reference_price": 8.0,
                "change_pct": 0.0,
                "volume": 0,
            }
        }
    )
    assert qp._classify_quote("002583", fetch2) == "stale"


def test_run_quote_probe_warns_but_exit_zero_on_partial():
    portfolio = {
        "holdings": [{"code": "600519", "shares": 100}],
        "watchlist": [{"code": "000001"}],
    }
    settings = {"trade_calendar": {"enabled": False}, "ops": {"quote_probe": {"push_warn": False}}}

    fetch = QuoteFetchResult(
        quotes={"600519": {"price": 1500.0, "change_pct": 0.1, "source": "eastmoney"}},
        errors={"000001": "no quote"},
        sources_used=["eastmoney"],
    )

    with patch.object(qp, "is_trading_day", return_value=(True, "ok")), patch(
        "agent_reach.daily_run.ops_quote_probe.fetch_quotes_map", return_value=fetch
    ):
        results, outcome, code = qp.run_quote_probe(
            settings=settings, skip_non_trading=False, portfolio=portfolio
        )

    assert code == 0
    probe = next(r for r in results if r.name == "quote_probe")
    assert probe.ok and probe.severity == "warn"
    assert outcome.per_code["000001"] == "missing"
    assert outcome.coverage_pct == 0.5


def test_run_quote_probe_skips_non_trading():
    settings = {"ops": {"quote_probe": {}}}
    with patch.object(qp, "is_trading_day", return_value=(False, "周末")):
        results, _outcome, code = qp.run_quote_probe(settings=settings, skip_non_trading=True)
    assert code == 0
    assert any("非交易日" in r.detail for r in results)