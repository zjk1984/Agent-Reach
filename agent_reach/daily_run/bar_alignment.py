# -*- coding: utf-8
"""Multi-symbol bar alignment to trading calendar (Backtrader data feed style)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import is_trading_day


def bar_alignment_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("bar_alignment") or {})


def bar_alignment_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return bar_alignment_cfg(settings).get("enabled", True) is not False


def assess_symbol_bar_quality(row: dict[str, Any]) -> str:
    price = row.get("price")
    if price is None:
        return "missing_price"
    try:
        if float(price) <= 0:
            return "missing_price"
    except (TypeError, ValueError):
        return "missing_price"
    volume = row.get("volume")
    if volume is None:
        return "missing_volume"
    try:
        if float(volume) <= 0:
            return "stale_volume"
    except (TypeError, ValueError):
        return "missing_volume"
    return "ok"


def annotate_enriched_bar_quality(
    enriched: dict[str, dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    if not bar_alignment_enabled(settings):
        return enriched
    out: dict[str, dict[str, Any]] = {}
    for code, row in enriched.items():
        merged = dict(row)
        merged["bar_quality"] = assess_symbol_bar_quality(merged)
        out[code] = merged
    return out


def filter_symbols_by_bar_quality(
    enriched: dict[str, dict[str, Any]],
    *,
    require_volume: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    kept: dict[str, dict[str, Any]] = {}
    dropped: list[str] = []
    for code, row in enriched.items():
        quality = str(row.get("bar_quality") or assess_symbol_bar_quality(row))
        if quality == "missing_price":
            dropped.append(code)
            continue
        if require_volume and quality in ("missing_volume", "stale_volume"):
            dropped.append(code)
            continue
        kept[code] = row
    return kept, dropped


def trading_days_between(start: date, end: date, *, settings: Optional[dict[str, Any]] = None) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        ok, _ = is_trading_day(cursor, settings=settings or {})
        if ok:
            days.append(cursor)
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return days
