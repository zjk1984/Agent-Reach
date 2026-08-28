# -*- coding: utf-8
"""Berkshire hooks for morning/close workflows."""

from __future__ import annotations

from typing import Any

from agent_reach.daily_run.berkshire.config import berkshire_enabled


def maybe_adjust_watchlist_morning(
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from agent_reach.daily_run.snapshot_builder import save_portfolio
    from agent_reach.daily_run.watchlist_manager import (
        adjust_watchlist,
        is_watchlist_adjust_enabled,
    )

    if not is_watchlist_adjust_enabled(settings):
        return portfolio, None
    wl = adjust_watchlist(portfolio, snapshot, settings, "morning")
    if wl.applied:
        save_portfolio(wl.portfolio)
        return wl.portfolio, wl.to_dict()
    return portfolio, wl.to_dict()


def run_close_berkshire(
    *,
    portfolio: dict[str, Any],
    symbol_results: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Thesis sync + drift for close symbol batch."""
    if not berkshire_enabled(settings):
        return {"skipped": True}

    from agent_reach.daily_run.berkshire.thesis_drift import detect_thesis_drift, render_drift_markdown
    from agent_reach.daily_run.berkshire.thesis_tracker import render_thesis_markdown, sync_thesis_from_snapshot

    sections: list[str] = []
    drifts: list[dict[str, Any]] = []
    synced: list[str] = []

    for row in symbol_results:
        inner = row.get("result") or {}
        snap = inner.get("snapshot") or {}
        code = snap.get("code") or row.get("code")
        if not code:
            continue
        sync_res = sync_thesis_from_snapshot(
            snap,
            settings=settings,
            portfolio=portfolio,
            phase="close",
        )
        if sync_res.get("applied"):
            synced.append(str(code))
        drift = detect_thesis_drift(str(code), snap, settings=settings)
        drifts.append(drift)
        if not drift.get("skipped"):
            sections.append(render_drift_markdown(drift))
        doc_path = sync_res.get("path")
        if doc_path:
            from agent_reach.daily_run.berkshire.thesis_tracker import load_thesis

            doc = load_thesis(str(code), settings)
            if doc:
                sections.append(render_thesis_markdown(doc))

    markdown = "\n\n".join(s for s in sections if s.strip())
    return {
        "synced_codes": synced,
        "drifts": drifts,
        "markdown": markdown,
    }
