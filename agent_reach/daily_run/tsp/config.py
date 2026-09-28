# -*- coding: utf-8 -*-
"""TSP Quant module configuration with fail-open defaults."""

from __future__ import annotations

from typing import Any, Optional


def tsp_quant_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Resolve TSP quant configuration with safe fail-open defaults."""
    if settings is None:
        try:
            from agent_reach.daily_run.settings import load_settings
            settings = load_settings()
        except Exception:
            settings = {}
    raw = dict((settings or {}).get("tsp_quant") or {})
    raw_intraday = dict(raw.get("intraday") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "regime_enabled": raw.get("regime_enabled", True) is not False,
        "deviation_enabled": raw.get("deviation_enabled", True) is not False,
        "mainline_enabled": raw.get("mainline_enabled", True) is not False,
        # Overlay session integration
        "session_regime_integration": raw.get("session_regime_integration", True) is not False,
        # Thresholds for deviation sentinels (warning buffer: alert when reaching warning_ratio of limit)
        "deviation_warning_ratio": float(raw.get("deviation_warning_ratio", 0.85)),
        # Hard block buy if deviation exceeds blocking ratio
        "deviation_block_buy_ratio": float(raw.get("deviation_block_buy_ratio", 0.90)),
        # Mainline ranking minimum limit up stocks to consider a sector as mainline
        "mainline_min_limit_ups": int(raw.get("mainline_min_limit_ups", 2)),
        # Intraday specific config
        "intraday": {
            "enabled": raw_intraday.get("enabled", True) is not False,
            "mainline_resonance_enabled": raw_intraday.get("mainline_resonance_enabled", True) is not False,
            "mainline_bonus_return_pct": float(raw_intraday.get("mainline_bonus_return_pct", 0.008)),
            "non_mainline_penalty_enabled": raw_intraday.get("non_mainline_penalty_enabled", True) is not False,
            "live_breadth_enabled": raw_intraday.get("live_breadth_enabled", True) is not False,
            "live_breadth_cache_ttl_seconds": int(raw_intraday.get("live_breadth_cache_ttl_seconds", 300)),
            "intraday_retreat_broken_rate": float(raw_intraday.get("intraday_retreat_broken_rate", 0.35)),
            "holding_deviation_alert": raw_intraday.get("holding_deviation_alert", True) is not False,
            "card_display_enabled": raw_intraday.get("card_display_enabled", True) is not False,
        },
        # Midday specific config
        "midday": {
            "enabled": dict(raw.get("midday") or {}).get("enabled", True) is not False,
            "card_display_enabled": dict(raw.get("midday") or {}).get("card_display_enabled", True) is not False,
            "handoff_integration": dict(raw.get("midday") or {}).get("handoff_integration", True) is not False,
        },
        # Weekly specific config
        "weekly": {
            "enabled": dict(raw.get("weekly") or {}).get("enabled", True) is not False,
            "sentiment_cycle_rollup": dict(raw.get("weekly") or {}).get("sentiment_cycle_rollup", True) is not False,
            "mainline_persistence_top_n": int(dict(raw.get("weekly") or {}).get("mainline_persistence_top_n", 5)),
        },
        # Forecast specific config
        "forecast": {
            "enabled": dict(raw.get("forecast") or {}).get("enabled", True) is not False,
            "regime_prior_enabled": dict(raw.get("forecast") or {}).get("regime_prior_enabled", True) is not False,
            "symbol_mainline_tagging": dict(raw.get("forecast") or {}).get("symbol_mainline_tagging", True) is not False,
            "deviation_lookahead_warning": dict(raw.get("forecast") or {}).get("deviation_lookahead_warning", True) is not False,
        },
    }
