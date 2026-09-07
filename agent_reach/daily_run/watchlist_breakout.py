# -*- coding: utf-8 -*-
"""Watchlist breakout buy lane — conditional auto-entry after 14:00 on strong movers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.snapshot_builder import _normalize_code


@dataclass
class WatchlistBreakoutResult:
    eligible: bool
    reason: str = ""
    max_position_pct: float = 5.0


def watchlist_breakout_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("intraday") or {}).get("watchlist_breakout") or {}
    min_lookback = raw.get("min_lookback_mss")
    if min_lookback is None:
        cfg_thr = (settings or {}).get("thresholds") or {}
        min_lookback = cfg_thr.get("aggressive_entry", 45.0)
    return {
        "enabled": raw.get("enabled", True) is not False,
        "min_change_pct": float(raw.get("min_change_pct", 8.0)),
        "min_lookback_mss": float(min_lookback),
        "after_hour": int(raw.get("after_hour", 14)),
        "after_minute": int(raw.get("after_minute", 0)),
        "max_position_pct": float(raw.get("max_position_pct", 5.0)),
        "allowed_trends": tuple(
            str(x) for x in (raw.get("allowed_trends") or ("rising", "turning_up", "mixed", "flat"))
        ),
    }


def _symbol_change_pct(snapshot: dict[str, Any], code: str) -> Optional[float]:
    norm = _normalize_code(code)
    for key in ("change_pct",):
        val = snapshot.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    pf = snapshot.get("portfolio") or {}
    for row in pf.get("holdings") or []:
        if _normalize_code(str(row.get("code", ""))) == norm:
            chg = row.get("change_pct")
            if chg is not None:
                try:
                    return float(chg)
                except (TypeError, ValueError):
                    pass
    for row in snapshot.get("watchlist") or []:
        if _normalize_code(str(row.get("code", ""))) == norm:
            chg = row.get("change_pct")
            if chg is not None:
                try:
                    return float(chg)
                except (TypeError, ValueError):
                    pass
    return None


def _is_watchlist_only(snapshot: dict[str, Any], code: str) -> bool:
    norm = _normalize_code(code)
    if not norm:
        return False
    held = {
        _normalize_code(str(h.get("code", "")))
        for h in (snapshot.get("portfolio") or {}).get("holdings") or []
    }
    if norm in held:
        return False
    watch = {
        _normalize_code(str(w.get("code", "")))
        for w in (snapshot.get("watchlist") or [])
    }
    return norm in watch


def _after_entry_window(cfg: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    ts = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    start_minutes = int(cfg["after_hour"]) * 60 + int(cfg["after_minute"])
    current = ts.hour * 60 + ts.minute
    return current >= start_minutes


def evaluate_watchlist_breakout_buy(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    settings: dict[str, Any],
    lookback_mss: float,
    trend: str,
    aggressive_entry: float,
    now: Optional[datetime] = None,
) -> WatchlistBreakoutResult:
    """Return eligibility for the watchlist breakout buy lane."""
    cfg = watchlist_breakout_cfg(settings)
    if not cfg["enabled"]:
        return WatchlistBreakoutResult(False, "watchlist_breakout disabled")

    code = _normalize_code(str(report.get("code") or snapshot.get("code") or ""))
    if not code:
        return WatchlistBreakoutResult(False, "missing symbol code")
    if not _is_watchlist_only(snapshot, code):
        return WatchlistBreakoutResult(False, "not a watchlist-only symbol")

    if not _after_entry_window(cfg, now=now):
        return WatchlistBreakoutResult(
            False,
            f"before {cfg['after_hour']:02d}:{cfg['after_minute']:02d} entry window",
        )

    change_pct = _symbol_change_pct(snapshot, code)
    min_chg = float(cfg["min_change_pct"])
    if change_pct is None or change_pct < min_chg:
        chg_label = "n/a" if change_pct is None else f"{change_pct:.2f}%"
        return WatchlistBreakoutResult(
            False,
            f"change {chg_label} < breakout min {min_chg:.1f}%",
        )

    mss_min = float(cfg["min_lookback_mss"])
    if float(lookback_mss) < mss_min:
        return WatchlistBreakoutResult(
            False,
            f"lookback MSS {lookback_mss:.0f} < breakout min {mss_min:.0f}",
        )

    if str(trend or "") not in cfg["allowed_trends"]:
        return WatchlistBreakoutResult(False, f"trend {trend} not in {cfg['allowed_trends']}")

    name = str(report.get("name") or code)
    return WatchlistBreakoutResult(
        True,
        (
            f"观察池突破：{name} 日涨 {change_pct:.1f}% ≥ {min_chg:.0f}%，"
            f"Lookback MSS {lookback_mss:.0f} ≥ {mss_min:.0f}，{cfg['after_hour']:02d}:"
            f"{cfg['after_minute']:02d} 后条件建仓"
        ),
        max_position_pct=float(cfg["max_position_pct"]),
    )
