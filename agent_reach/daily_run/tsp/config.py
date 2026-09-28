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
    }
