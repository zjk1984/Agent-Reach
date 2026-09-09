# -*- coding: utf-8
"""Bottleneck hunter lite — thematic watchlist candidates from super-trends (ROADMAP P2)."""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_THEMES: tuple[str, ...] = (
    "AI算力 光模块 HBM 液冷",
    "半导体设备 先进封装",
    "新能源 储能 电网",
)


def bottleneck_hunter_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("bottleneck_hunter") or {})
    themes = block.get("themes") or list(_DEFAULT_THEMES)
    return {
        "enabled": block.get("enabled", False) is True,
        "themes": [str(t) for t in themes if str(t).strip()],
        "max_queries": max(1, int(block.get("max_queries", 2))),
    }


def suggest_bottleneck_queries(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled

    cfg = bottleneck_hunter_cfg(settings)
    if not berkshire_enabled(settings, key="bottleneck_hunter") or not cfg.get("enabled"):
        return []
    return list(cfg["themes"])[: int(cfg["max_queries"])]
