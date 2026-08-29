# -*- coding: utf-8
"""Industry funnel — sector candidates → quality screen → top N watchlist."""

from __future__ import annotations

from typing import Any

from agent_reach.daily_run.berkshire.quality_screen import screen_from_snapshot
from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.watchlist_candidates import effective_watchlist_candidates


def rank_candidates_for_funnel(
    settings: dict[str, Any],
    *,
    enriched: dict[str, dict[str, Any]] | None = None,
    hot_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank watchlist candidates by MSS proxy + hot topic + quality pass."""
    candidates = effective_watchlist_candidates(settings)
    titles = " ".join(hot_titles or []).lower()
    scored: list[tuple[float, dict[str, Any]]] = []

    for cand in candidates:
        code = _normalize_code(str(cand.get("code", "")))
        if not code:
            continue
        row = dict(cand)
        if enriched and code in enriched:
            row = {**row, **enriched[code]}

        snap = {
            "code": code,
            "name": row.get("name"),
            "mss_final": row.get("mss_final"),
            "mss_breakdown": row.get("mss_breakdown"),
            "price": row.get("price"),
            "change_pct": row.get("change_pct"),
            "sector": row.get("sector"),
        }
        qs = screen_from_snapshot(snap, enriched=row)
        if not qs.passed and "数据不足" not in qs.reason:
            continue

        score = float(row.get("mss_final") or 50)
        kws = cand.get("keywords") or []
        if titles and any(str(k).lower() in titles for k in kws):
            score += 5
        if qs.passed:
            score += 3
        scored.append((score, cand))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def funnel_select_watchlist(
    settings: dict[str, Any],
    *,
    enriched: dict[str, dict[str, Any]] | None = None,
    hot_titles: list[str] | None = None,
    target_count: int | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.watchlist_manager import watchlist_min_size, watchlist_max_size

    wl_cfg = settings.get("watchlist") or {}
    target = target_count
    if target is None:
        target = int(wl_cfg.get("funnel_target") or watchlist_min_size(settings))
    target = max(target, watchlist_min_size(settings))
    cap = watchlist_max_size(settings)

    ranked = rank_candidates_for_funnel(settings, enriched=enriched, hot_titles=hot_titles)
    selected = ranked[: min(target, cap)]
    return {
        "target": target,
        "candidates_scored": len(ranked),
        "selected": selected,
        "codes": [_normalize_code(str(c.get("code", ""))) for c in selected],
    }
