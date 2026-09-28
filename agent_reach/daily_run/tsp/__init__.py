# -*- coding: utf-8 -*-
"""TSP (Tick-Stock-Panel) quant adapter package.

Lightweight quant indicators and regime probe inspired by tick-stock-panel:
- 6-phase market sentiment regime (freezing, launching, main_up, climax, retreat, repair)
- Sector & concept mainline scoring from limit-up ladder
- Exchange abnormal move price deviation monitor (3-day +/-20%, 10-day +100%/-50%, 30-day +200%/-70%)
- Fail-open fallback design compatible with daily-run harness and session overlay.
"""

from __future__ import annotations

from agent_reach.daily_run.tsp.market_regime import (
    classify_tsp_market_phase,
    compute_ladder_promotion_rates,
    compute_tsp_market_phase,
    format_tsp_regime_summary,
    map_tsp_phase_to_session_regime,
)
from agent_reach.daily_run.tsp.mainline_ranker import (
    rank_tsp_mainlines,
    score_mainline_sector,
)
from agent_reach.daily_run.tsp.deviation_monitor import (
    check_portfolio_deviation_risk,
    compute_exchange_deviation_risk,
    format_deviation_alert_lines,
)
from agent_reach.daily_run.tsp.call_auction import (
    evaluate_call_auction_divergence,
)
from agent_reach.daily_run.tsp.config import tsp_quant_cfg
from agent_reach.daily_run.tsp.intraday_sentinel import (
    TSPMainlineMatch,
    check_intraday_retreat_risk,
    check_ladder_relay_guard,
    clear_intraday_sentinel_cache,
    format_tsp_intraday_card_markdown,
    get_live_market_breadth_and_phase,
    is_symbol_in_top_n_mainlines,
    match_symbol_tsp_mainline,
)

__all__ = [
    "classify_tsp_market_phase",
    "compute_ladder_promotion_rates",
    "compute_tsp_market_phase",
    "format_tsp_regime_summary",
    "map_tsp_phase_to_session_regime",
    "rank_tsp_mainlines",
    "score_mainline_sector",
    "check_portfolio_deviation_risk",
    "compute_exchange_deviation_risk",
    "format_deviation_alert_lines",
    "evaluate_call_auction_divergence",
    "tsp_quant_cfg",
    "TSPMainlineMatch",
    "get_live_market_breadth_and_phase",
    "match_symbol_tsp_mainline",
    "is_symbol_in_top_n_mainlines",
    "check_intraday_retreat_risk",
    "check_ladder_relay_guard",
    "clear_intraday_sentinel_cache",
    "format_tsp_intraday_card_markdown",
]
