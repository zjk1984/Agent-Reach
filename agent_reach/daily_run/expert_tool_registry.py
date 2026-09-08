# -*- coding: utf-8
"""Per-expert channel allowlist (AutoHedge-style tool isolation)."""

from __future__ import annotations

from typing import FrozenSet

# Channel ids used by channel_helpers / expert plugins.
EXPERT_CHANNELS: dict[str, FrozenSet[str]] = {
    "sentiment": frozenset({"exa", "xueqiu", "hot_news", "eastmoney"}),
    "macro": frozenset({"exa", "hot_news"}),
    "fundamental": frozenset({"exa", "eastmoney"}),
    "industry": frozenset({"exa", "eastmoney"}),
    "technical": frozenset(),
    "quant": frozenset(),
    "risk": frozenset(),
    "identifier": frozenset(),
}


def channel_allowed(expert_name: str, channel: str) -> bool:
    """Return True when ``channel`` may be used by ``expert_name``."""
    allowed = EXPERT_CHANNELS.get(str(expert_name or "").strip().lower())
    if allowed is None:
        return False
    if not allowed:
        return False
    return str(channel or "").strip().lower() in allowed


def list_expert_channels(expert_name: str) -> list[str]:
    allowed = EXPERT_CHANNELS.get(str(expert_name or "").strip().lower())
    if not allowed:
        return []
    return sorted(allowed)
