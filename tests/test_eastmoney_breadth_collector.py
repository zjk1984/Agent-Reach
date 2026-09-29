# -*- coding: utf-8
"""Tests for Eastmoney clist breadth fallback (D3 intraday width)."""

from unittest.mock import patch

import pytest

from agent_reach.daily_run.eastmoney_breadth_collector import (
    eastmoney_breadth_fallback_enabled,
    fetch_eastmoney_breadth_pool,
    format_breadth_source_label,
    merge_akshare_pool_enrichment,
)
from agent_reach.daily_run.tsp.intraday_sentinel import (
    clear_intraday_sentinel_cache,
    get_live_market_breadth_and_phase,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_intraday_sentinel_cache()
    yield
    clear_intraday_sentinel_cache()


def test_fetch_eastmoney_breadth_pool_from_clist():
    sample_stocks = [
        {"code": "600519", "name": "贵州茅台", "change_pct": 10.0, "industry": "白酒"},
        {"code": "000001", "name": "平安银行", "change_pct": 1.2, "industry": "银行"},
        {"code": "300001", "name": "特锐德", "change_pct": -10.0, "industry": "电气设备"},
        {"code": "688001", "name": "华兴源创", "change_pct": 9.9, "industry": "半导体"},
    ]

    with patch(
        "agent_reach.daily_run.eastmoney_market.fetch_all_stocks_resilient",
        return_value=(sample_stocks, "eastmoney", []),
    ), patch(
        "agent_reach.daily_run.eastmoney_market.fetch_north_flow_resilient",
        return_value=({"net_yi": 12.0, "source": "eastmoney_north"}, []),
    ):
        pool = fetch_eastmoney_breadth_pool(settings={})

    assert pool["up_count"] == 3
    assert pool["down_count"] == 1
    assert pool["limit_up"] == 2
    assert pool["limit_down"] == 1
    assert pool["source"] == "eastmoney_clist"
    assert pool["ladder_degraded"] is True
    assert pool["limit_degraded"] is True
    assert len(pool["limit_up_stocks"]) == 2


def test_merge_akshare_pool_enrichment_prefers_ladder():
    em_pool = {
        "limit_up": 20,
        "limit_down": 2,
        "broken_count": 4,
        "broken_rate": 0.1667,
        "up_count": 800,
        "down_count": 4000,
        "flat_count": 100,
        "limit_up_stocks": [{"code": "600519", "change_pct": 10.0, "industry": "白酒"}],
        "source": "eastmoney_clist",
        "ladder_degraded": True,
        "limit_degraded": True,
    }
    ak_pool = {
        "limit_up": 33,
        "limit_down": 11,
        "broken_count": 8,
        "broken_rate": 0.195,
        "up_count": 862,
        "down_count": 4245,
        "flat_count": 50,
        "limit_up_stocks": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "change_pct": 10.0,
                "industry": "白酒",
                "consecutive_limit_ups": 3,
            }
        ],
        "source": "akshare_legu+pool",
    }

    merged = merge_akshare_pool_enrichment(em_pool, ak_pool)

    assert merged["limit_up"] == 33
    assert merged["broken_count"] == 8
    assert merged["up_count"] == 862
    assert merged["ladder_degraded"] is False
    assert merged["limit_degraded"] is False
    assert merged["source"] == "eastmoney_clist+akshare_legu+pool"
    assert merged["limit_up_stocks"][0]["consecutive_limit_ups"] == 3


def test_format_breadth_source_label():
    label = format_breadth_source_label(
        {
            "source": "eastmoney_clist+akshare_legu+pool",
            "ladder_degraded": False,
            "limit_degraded": False,
        }
    )
    assert "东财宽度" in label
    assert "akshare池" in label


def test_intraday_eastmoney_fallback_when_akshare_empty():
    em_pool = {
        "limit_up": 28,
        "limit_down": 5,
        "broken_count": 6,
        "broken_rate": 0.1765,
        "up_count": 900,
        "down_count": 4100,
        "flat_count": 80,
        "limit_up_stocks": [
            {"code": "600519", "name": "贵州茅台", "change_pct": 10.0, "industry": "白酒"},
        ],
        "source": "eastmoney_clist",
        "ladder_degraded": True,
        "limit_degraded": True,
    }

    with patch(
        "agent_reach.daily_run.limit_pool_collector.fetch_akshare_limit_pools",
        side_effect=RuntimeError("akshare empty"),
    ), patch(
        "agent_reach.daily_run.eastmoney_breadth_collector.fetch_eastmoney_breadth_pool",
        return_value=em_pool,
    ):
        result = get_live_market_breadth_and_phase(force_refresh=True)

    assert result["limit_up"] == 28
    assert result["up_count"] == 900
    assert result["down_count"] == 4100
    assert result["source"] == "eastmoney_clist"
    assert result["ladder_degraded"] is True
    assert result["limit_degraded"] is True


def test_eastmoney_breadth_fallback_respects_config():
    assert eastmoney_breadth_fallback_enabled(
        {"market_review": {"eastmoney_breadth_fallback": False}}
    ) is False
    assert eastmoney_breadth_fallback_enabled(
        {
            "market_review": {"eastmoney_breadth_fallback": True},
            "tsp_quant": {"intraday": {"eastmoney_breadth_fallback": False}},
        }
    ) is False
