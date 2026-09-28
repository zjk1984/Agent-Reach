# -*- coding: utf-8 -*-
"""Tests for Phase-2.9 MarketDataRouter and EnrichedSymbolProfile chain."""

from unittest.mock import patch

import pytest

from agent_reach.daily_run.data_router import (
    MarketDataRouter,
    clear_market_data_router,
    get_market_data_router,
)
from agent_reach.daily_run.symbols import (
    EnrichedSymbolProfile,
    apply_enriched_replay_context,
    build_enriched_symbols,
    merge_enriched_row,
)


@pytest.fixture(autouse=True)
def _reset_router():
    clear_market_data_router()
    yield
    clear_market_data_router()


def test_enriched_symbol_profile_from_dict():
    row = {
        "name": "澜起科技",
        "price": 220.0,
        "change_pct": 5.0,
        "consecutive_limit_ups": 2,
        "distance_to_limit_pct": 8.5,
        "risk_level": "warning",
        "mss_final": 62.0,
    }
    profile = EnrichedSymbolProfile.from_dict("688008", row)
    assert profile.code == "688008"
    assert profile.name == "澜起科技"
    assert profile.consecutive_boards == 2
    assert profile.distance_to_limit_pct == 8.5
    assert profile.deviation_risk_level == "warning"
    assert profile.mss_score == 62.0


def test_merge_enriched_row_and_replay_context():
    base = {"code": "600000", "name": "浦发银行", "verdict": "观察"}
    enriched = {
        "price": 10.5,
        "change_pct": 2.1,
        "is_panic_dumping": True,
        "distance_to_limit_pct": 3.2,
        "consecutive_boards": 2,
    }
    merged = merge_enriched_row(base, enriched)
    assert merged["price"] == 10.5
    assert merged["is_panic_dumping"] is True

    entry = {
        "code": "600000",
        "name": "浦发银行",
        "verdict": "买入",
        "enriched": {"open_pct": -5.5, "auction_ratio_pct": 1.2},
    }
    snap, report = apply_enriched_replay_context(entry, {"portfolio": {}}, {"600000": enriched})
    assert snap["price"] == 10.5
    assert snap["open_pct"] == -5.5
    assert report["is_panic_dumping"] is True
    assert report["verdict"] == "买入"


def test_build_enriched_symbols_includes_d6_fields():
    snapshot = {
        "portfolio": {
            "holdings": [
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "shares": 100,
                    "cost": 200.0,
                    "price": 220.0,
                    "change_pct": 5.0,
                    "cumulative_3d_pct": 18.0,
                }
            ],
            "watchlist": [],
        }
    }
    enriched = build_enriched_symbols(snapshot, settings={"tsp_quant": {"enabled": True}})
    row = enriched["688008"]
    assert row["is_holding"] is True
    assert "distance_to_limit_pct" in row
    assert "deviation_risk_level" in row or "risk_level" in row


def test_market_data_router_provenance_status():
    router = MarketDataRouter(settings={})
    prov = router.get_provenance_status()
    assert "d1_quotes" in prov
    assert "d6_deviation" in prov
    assert prov["d6_deviation"]["status"] == "healthy"


def test_market_data_router_d1_quotes_cache():
    router = MarketDataRouter(settings={})
    mock_quotes = {
        "600000": {"code": "600000", "name": "浦发银行", "price": 10.0, "change_pct": 1.0},
    }

    with patch("agent_reach.daily_run.data_router.fetch_quotes_map") as mock_fetch:
        mock_fetch.return_value.quotes = mock_quotes
        res1 = router.get_live_quotes(["600000"])
        res2 = router.get_live_quotes(["600000"])
        assert res1["600000"]["price"] == 10.0
        assert mock_fetch.call_count == 1
        assert res2["600000"]["price"] == 10.0


def test_get_market_data_router_singleton():
    r1 = get_market_data_router({"foo": 1})
    r2 = get_market_data_router()
    assert r1 is r2


def test_intraday_friction_whatif_tsp_guard_attribution():
    from agent_reach.daily_run.sell_rules_whatif import (
        IntradayFrictionWhatIfResult,
        summarize_intraday_friction_for_harness,
    )

    result = IntradayFrictionWhatIfResult(
        as_of="2026-09-28",
        policy_note="test",
        tsp_guard_blocks=2,
        tsp_guard_kinds={"tsp_auction_panic": 1, "tsp_ladder_broken": 1},
        rows=[{"code": "600000", "actual_action": "hold", "evolved_action": "hold"}],
    )
    harness = summarize_intraday_friction_for_harness(result)
    assert any("TSP 量化防线" in m for m in harness["memory"])
    assert any("TSP 防线" in p for p in harness["playbook"])
