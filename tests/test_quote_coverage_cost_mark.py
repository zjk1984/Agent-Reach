# -*- coding: utf-8
"""Quote mark validation — cost must not pass as live close (Feishu 台账 regression)."""

from agent_reach.daily_run.quote_coverage import (
    holding_close_mark_price,
    mark_price_from_row,
    symbol_has_live_quote,
)


class TestCostMustNotBeLiveMark:
    def test_symbol_has_live_quote_rejects_price_equal_cost_even_with_named_source(self):
        row = {
            "code": "002583",
            "cost": 12.618,
            "price": 12.618,
            "quote_source": "eastmoney",
        }
        assert symbol_has_live_quote(row, {}) is False
        assert mark_price_from_row(row, {}) is None

    def test_holding_close_mark_prefers_enriched_over_stamped_cost(self):
        holding = {
            "code": "000725",
            "name": "京东方A",
            "shares": 900,
            "cost": 5.7364,
            "price": 5.7364,
            "quote_source": "xueqiu",
        }
        enriched = {"000725": {"price": 4.12, "quote_source": "eastmoney", "change_pct": -0.8}}
        assert holding_close_mark_price(holding, enriched) == 4.12

    def test_close_ledger_row_shows_enriched_close_not_cost(self):
        from agent_reach.daily_run.close_cards import collect_holdings_ledger_rows

        pf = {
            "end_total": 100000.0,
            "holdings": [
                {
                    "code": "002583",
                    "name": "海能达",
                    "shares": 2500,
                    "cost": 12.618,
                    "price": 12.618,
                    "quote_source": "eastmoney",
                    "market_value": 21250.0,
                },
                {
                    "code": "000725",
                    "name": "京东方A",
                    "shares": 300,
                    "cost": 5.7364,
                    "price": 5.7364,
                    "quote_source": "eastmoney",
                    "market_value": 1720.92,
                },
            ],
        }
        enriched = {
            "002583": {"price": 8.51, "quote_source": "eastmoney", "change_pct": 1.2},
            "000725": {"price": 4.08, "quote_source": "eastmoney", "change_pct": -0.5},
        }
        rows = collect_holdings_ledger_rows(pf, enriched=enriched)
        by_code = {r["code"]: r for r in rows}
        assert by_code["002583"]["close_price"] == 8.51
        assert by_code["000725"]["close_price"] == 4.08