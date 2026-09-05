# -*- coding: utf-8
"""Safe retention policy for daily_run.db and companion files."""

from __future__ import annotations

from typing import Any, Optional

# L0 kinds that must never be deleted by automated prune (even when distilled).
PROTECTED_L0_KINDS: tuple[str, ...] = (
    "trade",
    "pnl_history",
    "capital_event",
    "portfolio",
    "rejected_strategy",
)

# L0 kinds eligible for deletion once distilled and older than l0_keep_days.
DEFAULT_PRUNE_L0_KINDS: tuple[str, ...] = (
    "job_run",
    "harness_overlay_diff",
    "harness_memory_diff",
    "harness_audit",
    "harness_refinement",
    "intraday_scan",
    "intraday_state",
    "experience",
    "skill_changelog",
    "session_overlay",
    "daily_trade_state",
)

# High-volume L1 atoms safe to trim (summary already in harness_state / L2).
DEFAULT_PRUNE_L1_KINDS: tuple[str, ...] = (
    "harness_overlay_diff",
    "harness_memory_diff",
    "harness_audit",
)

PROTECTED_L1_KINDS: tuple[str, ...] = (
    "trade_action",
    "trade_batch",
    "trade_case",
    "experience_summary",
    "experience_rule",
    "portfolio_snapshot",
    "job_run",
)


def effective_prune_l0_kinds(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    raw = list(cfg.get("prune_l0_kinds") or DEFAULT_PRUNE_L0_KINDS)
    protected = set(cfg.get("protected_l0_kinds") or PROTECTED_L0_KINDS)
    return [k for k in raw if k not in protected]


def effective_prune_l1_kinds(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    if cfg.get("l1_prune_enabled") is False:
        return []
    raw = list(cfg.get("prune_l1_kinds") or DEFAULT_PRUNE_L1_KINDS)
    protected = set(cfg.get("protected_l1_kinds") or PROTECTED_L1_KINDS)
    return [k for k in raw if k not in protected]
