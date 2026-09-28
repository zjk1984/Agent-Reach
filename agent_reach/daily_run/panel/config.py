# -*- coding: utf-8 -*-
"""Configuration reader for daily-run mission control panel."""

from __future__ import annotations

import os
from typing import Any, Optional

from agent_reach.daily_run.settings import effective_settings, load_settings

_DEFAULT_PANEL_CFG: dict[str, Any] = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 8788,
    "url": "http://127.0.0.1:8788",
    "card_link_enabled": True,
}


def panel_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return effective panel config merged with defaults."""
    raw = settings if settings is not None else load_settings()
    eff = effective_settings(raw) if raw else {}
    user_block = eff.get("panel")
    if not isinstance(user_block, dict):
        user_block = {}
    merged = dict(_DEFAULT_PANEL_CFG)
    merged.update(user_block)
    return merged


def panel_url(settings: Optional[dict[str, Any]] = None) -> str:
    """Return the configured or default base URL for the web panel."""
    url = os.environ.get("AGENT_REACH_PANEL_URL", "").strip()
    if url:
        return url
    cfg = panel_cfg(settings)
    return str(cfg.get("url") or f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8788)}")


def panel_card_link_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    """Check whether card link to the panel should be attached to Feishu notifications."""
    cfg = panel_cfg(settings)
    return bool(cfg.get("enabled", True) and cfg.get("card_link_enabled", True))
