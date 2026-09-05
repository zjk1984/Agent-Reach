# -*- coding: utf-8
"""Quant chain health checks for daily-run overlay / handoff / week_open."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai


def _status(ok: bool, *, warn: bool = False) -> str:
    if ok:
        return "ok"
    return "warn" if warn else "error"


def check_close_handoff_seed(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.close_morning_handoff import load_close_handoff
    from agent_reach.daily_run.prior_close import prev_trading_day

    d = as_of or today_shanghai()
    prev = prev_trading_day(d, settings=settings or {})
    handoff = load_close_handoff(close_day=prev, settings=settings) or {}
    seed = handoff.get("next_day_session_seed") or {}
    ok = bool(seed.get("regime"))
    return {
        "id": "close_handoff_seed",
        "status": _status(ok, warn=not ok),
        "message": (
            f"前收 handoff seed: {seed.get('regime') or '缺失'}"
            if ok
            else f"{prev.isoformat()} 收盘 handoff 无 next_day_session_seed"
        ),
        "close_day": prev.isoformat(),
    }


def check_week_open_active(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.week_open_overlay import load_week_open_overlay

    d = as_of or today_shanghai()
    overlay = load_week_open_overlay(as_of=d) or {}
    ws = str(overlay.get("week_start") or "")
    we = str(overlay.get("week_end") or "")
    in_week = True
    if ws and we:
        try:
            in_week = date.fromisoformat(ws) <= d <= date.fromisoformat(we)
        except ValueError:
            in_week = True
    active = bool(overlay.get("enabled") is not False and overlay.get("regime") and in_week)
    return {
        "id": "week_open_overlay",
        "status": _status(active or not in_week, warn=not active and in_week),
        "message": (
            f"week_open {overlay.get('regime') or 'neutral'} ({ws}~{we})"
            if active
            else ("week_open 本周未生效" if in_week else f"week_open 不在有效期 ({ws}~{we})")
        ),
    }


def check_overlay_coverage(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.overlay_telemetry import aggregate_week_overlay_stats

    d = as_of or today_shanghai()
    ok_trade, _ = is_trading_day(d, settings=settings or {})
    if not ok_trade:
        return {
            "id": "overlay_coverage",
            "status": "ok",
            "message": f"{d.isoformat()} 非交易日，跳过 overlay 覆盖检查",
        }

    stats = aggregate_week_overlay_stats(d, d, settings=settings)
    quality = str(stats.get("data_quality") or "missing")
    log_days = int(stats.get("log_days") or 0)
    ok = quality in ("ok", "partial") and log_days > 0
    return {
        "id": "overlay_coverage",
        "status": _status(ok, warn=quality == "partial"),
        "message": (
            f"今日 overlay 遥测: {quality}, log_days={log_days}, "
            f"patch={stats.get('threshold_patch_days', 0)}"
        ),
        "stats": stats,
    }


def check_overlay_db_file_consistency(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.overlay_telemetry import _load_daily_record, _log_path
    from agent_reach.daily_run.storage.config import storage_enabled
    from agent_reach.daily_run.storage.readers import read_session_overlay_daily

    if not storage_enabled(settings):
        return {
            "id": "overlay_db_file",
            "status": "ok",
            "message": "storage 未启用，跳过 DB/文件对账",
        }

    d = as_of or today_shanghai()
    file_row = _load_daily_record(d)
    db_row = read_session_overlay_daily(d, settings=settings)
    if not _log_path(d).is_file() and not db_row:
        return {
            "id": "overlay_db_file",
            "status": "warn",
            "message": f"{d.isoformat()} 无 overlay 文件也无 DB 记录",
        }

    file_seen = bool((file_row.get("morning") or {}).get("seen") or (file_row.get("afternoon") or {}).get("seen"))
    db_seen = bool((db_row or {}).get("morning", {}).get("seen") or (db_row or {}).get("afternoon", {}).get("seen"))
    if file_seen == db_seen:
        return {
            "id": "overlay_db_file",
            "status": "ok",
            "message": f"{d.isoformat()} DB/文件 overlay 一致 (seen={file_seen})",
        }
    return {
        "id": "overlay_db_file",
        "status": "warn",
        "message": f"{d.isoformat()} DB/文件 overlay 不一致 file_seen={file_seen} db_seen={db_seen}",
    }


def run_quant_chain_doctor(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    checks = [
        check_close_handoff_seed(as_of=as_of, settings=settings),
        check_week_open_active(as_of=as_of, settings=settings),
        check_overlay_coverage(as_of=as_of, settings=settings),
        check_overlay_db_file_consistency(as_of=as_of, settings=settings),
    ]
    worst = "ok"
    for c in checks:
        st = str(c.get("status") or "ok")
        if st == "error":
            worst = "error"
        elif st == "warn" and worst == "ok":
            worst = "warn"
    return {
        "as_of": (as_of or today_shanghai()).isoformat(),
        "status": worst,
        "checks": checks,
    }


def format_quant_chain_doctor(report: dict[str, Any]) -> str:
    lines = ["Quant chain doctor", "=" * 32]
    icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}
    for check in report.get("checks") or []:
        st = str(check.get("status") or "ok")
        lines.append(f"{icon.get(st, '?')} {check.get('id')}: {check.get('message')}")
    lines.append(f"Overall: {report.get('status')}")
    return "\n".join(lines)
