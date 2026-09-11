# -*- coding: utf-8
"""Freqtrade-inspired protection plugin chain for daily-run intraday."""

from agent_reach.daily_run.protections.engine import (
    evaluate_protections,
    protection_block_reason,
    protection_overlay_note,
    record_protection_hits,
)
from agent_reach.daily_run.protections.sector_mss_mismatch import protection_verdict_cap
from agent_reach.daily_run.protections.iprotection import ProtectionReturn

__all__ = [
    "ProtectionReturn",
    "evaluate_protections",
    "protection_block_reason",
    "protection_overlay_note",
    "protection_verdict_cap",
]
