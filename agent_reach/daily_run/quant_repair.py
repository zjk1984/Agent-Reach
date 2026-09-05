# -*- coding: utf-8
"""Repair quant chain artifacts: close handoff seeds, week_open overlay."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.close_morning_handoff import close_handoff_path, save_close_handoff
from agent_reach.daily_run.trade_calendar import today_shanghai


def _handoff_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "handoff"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def portfolio_summary_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    """Best-effort portfolio_summary for seed rebuild from legacy close handoff JSON."""
    summary: dict[str, Any] = {}
    total = _optional_float(handoff.get("portfolio_total"))
    if total is not None:
        summary["end_total"] = total

    for item in handoff.get("tomorrow_focus") or []:
        if str(item.get("kind") or "") != "narrative":
            continue
        text = str(item.get("text") or "")
        match = re.search(r"¥(-?[\d,]+).*?（(-?[\d.]+)%）", text)
        if match:
            summary["daily_pnl"] = float(match.group(1).replace(",", ""))
            summary["daily_pnl_pct"] = float(match.group(2))
            break

    return summary


def repair_close_handoff_seeds(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.quant_calibration import build_next_day_session_seed

    cfg = settings or {}
    repaired: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    paths = sorted(_handoff_dir().glob("close_*.json"))
    for path in paths:
        day_s = path.stem.replace("close_", "", 1)
        try:
            close_day = date.fromisoformat(day_s)
        except ValueError:
            skipped.append(path.name)
            continue
        try:
            handoff = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if not isinstance(handoff, dict):
            skipped.append(path.name)
            continue
        existing = handoff.get("next_day_session_seed")
        if isinstance(existing, dict) and existing.get("regime"):
            skipped.append(day_s)
            continue

        summary = portfolio_summary_from_handoff(handoff)
        seed = build_next_day_session_seed(
            portfolio_summary=summary,
            settings=cfg,
            close_day=close_day,
        )
        updated = {**handoff, "next_day_session_seed": seed}
        save_close_handoff(updated)
        repaired.append(day_s)

    last = _handoff_dir() / "last_close_handoff.json"
    if repaired and last.is_file():
        try:
            latest_day = max(date.fromisoformat(d) for d in repaired)
            hit = json.loads(close_handoff_path(latest_day).read_text(encoding="utf-8"))
            if isinstance(hit, dict):
                save_close_handoff(hit)
        except (ValueError, json.JSONDecodeError, OSError):
            pass

    return {
        "repaired": repaired,
        "skipped": skipped,
        "errors": errors,
    }


def repair_week_open_overlay(
    *,
    settings: Optional[dict[str, Any]] = None,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.week_forecast import load_active_forecast
    from agent_reach.daily_run.week_open_overlay import (
        build_and_save_week_open_overlay,
        load_week_open_overlay,
        week_open_overlay_path,
    )

    cfg = settings if settings is not None else load_settings()
    d = as_of or today_shanghai()
    existing = load_week_open_overlay(as_of=d) or {}
    ws = str(existing.get("week_start") or "")
    we = str(existing.get("week_end") or "")
    if existing.get("regime") and ws and we:
        try:
            if date.fromisoformat(ws) <= d <= date.fromisoformat(we):
                return {
                    "status": "skipped",
                    "reason": "week_open already active",
                    "week_start": ws,
                    "path": str(week_open_overlay_path(date.fromisoformat(ws))),
                }
        except ValueError:
            pass

    forecast = load_active_forecast(d)
    if not forecast:
        return {"status": "error", "reason": "no active forecast for current week"}

    path = build_and_save_week_open_overlay(forecast, settings=cfg)
    payload = load_week_open_overlay(as_of=d) or {}
    return {
        "status": "ok",
        "week_start": payload.get("week_start"),
        "week_end": payload.get("week_end"),
        "regime": payload.get("regime"),
        "path": str(path) if path else "",
    }


def repair_quant_chain(
    *,
    settings: Optional[dict[str, Any]] = None,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    handoff = repair_close_handoff_seeds(settings=settings)
    week_open = repair_week_open_overlay(settings=settings, as_of=as_of)
    return {"close_handoff": handoff, "week_open": week_open}
