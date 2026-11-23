# -*- coding: utf-8
"""Stash and attach watchlist_adjust fields on schedule run manifests (AR-41)."""

from __future__ import annotations

import contextvars
from typing import Any, Optional

_PENDING: contextvars.ContextVar[Optional[dict[str, Any]]] = contextvars.ContextVar(
    "watchlist_adjust_manifest_pending",
    default=None,
)


def record_watchlist_adjust_for_manifest(
    *,
    watchlist_adjust: Optional[dict[str, Any]],
    watchlist_adjust_summary: dict[str, Any],
) -> None:
    """Remember adjust output for this schedule run (success or failure manifest)."""
    _PENDING.set(
        {
            "watchlist_adjust": watchlist_adjust,
            "watchlist_adjust_summary": watchlist_adjust_summary,
        }
    )


def clear_watchlist_adjust_manifest_pending() -> None:
    _PENDING.set(None)


def attach_watchlist_adjust_to_manifest_payload(payload: dict[str, Any]) -> None:
    """Ensure watchlist_adjust + summary appear on the manifest payload (in-place)."""
    pending = _PENDING.get() or {}
    summary = payload.get("watchlist_adjust_summary")
    adjust = payload.get("watchlist_adjust")

    if summary is None and pending.get("watchlist_adjust_summary") is not None:
        summary = pending["watchlist_adjust_summary"]
        payload["watchlist_adjust_summary"] = summary
    if adjust is None and pending.get("watchlist_adjust") is not None:
        adjust = pending["watchlist_adjust"]
        payload["watchlist_adjust"] = adjust

    if payload.get("watchlist_adjust_summary") is None and isinstance(adjust, dict):
        from agent_reach.daily_run.watchlist_manager import (
            watchlist_adjust_manifest_summary,
            watchlist_adjust_result_from_dict,
        )

        payload["watchlist_adjust_summary"] = watchlist_adjust_manifest_summary(
            watchlist_adjust_result_from_dict(adjust),
            enabled=True,
        )

    result = payload.get("result")
    if isinstance(result, dict):
        if result.get("watchlist_adjust_summary") is None and payload.get("watchlist_adjust_summary"):
            result["watchlist_adjust_summary"] = payload["watchlist_adjust_summary"]
        if result.get("watchlist_adjust") is None and payload.get("watchlist_adjust"):
            result["watchlist_adjust"] = payload["watchlist_adjust"]