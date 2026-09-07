# -*- coding: utf-8 -*-
"""Session regime helpers (defensive / neutral / supportive) from harness runtime."""

from __future__ import annotations

from typing import Any, Optional


def merged_session_regime(settings: Optional[dict[str, Any]] = None) -> str:
    """Return merged session regime from harness_runtime overlays."""
    runtime = (settings or {}).get("harness_runtime") or {}
    seed = runtime.get("session_seed") or {}
    merged = seed.get("merged_regime") or seed.get("seed_regime")
    if merged:
        return str(merged)
    for key in ("pm_session", "am_open", "week_open"):
        block = runtime.get(key) or {}
        regime = block.get("merged_regime") or block.get("regime")
        if regime:
            return str(regime)
    return "neutral"


def supportive_regime_active(settings: Optional[dict[str, Any]] = None) -> bool:
    return merged_session_regime(settings) == "supportive"


def defensive_regime_active(settings: Optional[dict[str, Any]] = None) -> bool:
    return merged_session_regime(settings) == "defensive"
