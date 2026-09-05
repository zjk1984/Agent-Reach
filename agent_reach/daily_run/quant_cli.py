# -*- coding: utf-8
"""CLI helpers: quant chain doctor and weekly reconcile."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai


def add_quant_subparser(p_daily_sub: argparse._SubParsersAction) -> None:
    p_quant = p_daily_sub.add_parser("quant", help="Quant overlay chain doctor and reconcile")
    p_quant_sub = p_quant.add_subparsers(dest="quant_action", required=True)

    p_doc = p_quant_sub.add_parser("doctor", help="Check close seed / week_open / overlay coverage")
    p_doc.add_argument("--json", action="store_true", help="JSON output")

    p_rec = p_quant_sub.add_parser("reconcile", help="Compare intraday scans vs overlay telemetry for a week")
    p_rec.add_argument("--week-start", default="", help="Week start ISO date (default: last Mon)")
    p_rec.add_argument("--json", action="store_true", help="JSON output")

    p_rep = p_quant_sub.add_parser("repair", help="Backfill missing close seeds and week_open overlay")
    p_rep.add_argument("--json", action="store_true", help="JSON output")


def _default_week_start(as_of: Optional[date] = None) -> date:
    d = as_of or today_shanghai()
    return d - timedelta(days=d.weekday())


def reconcile_quant_week(
    week_start: date,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.overlay_telemetry import _load_daily_record, aggregate_week_overlay_stats
    from agent_reach.daily_run.storage.config import storage_enabled
    from agent_reach.daily_run.storage.readers import read_session_overlay_daily

    cfg = settings or {}
    week_end = week_start + timedelta(days=4)
    overlay_stats = aggregate_week_overlay_stats(week_start, week_end, settings=cfg)

    days_out: list[dict[str, Any]] = []
    day = week_start
    while day <= week_end:
        ok_trade, _ = is_trading_day(day, settings=cfg)
        if not ok_trade:
            day += timedelta(days=1)
            continue

        intraday_scans = 0
        overlay_events = 0
        if storage_enabled(cfg):
            try:
                from agent_reach.daily_run.storage import get_store

                store = get_store(cfg)
                rows = store.query_l0_events(
                    kind="intraday_scan",
                    since=day.isoformat(),
                    limit=500,
                )
                intraday_scans = sum(
                    1 for r in rows if str(r.get("at") or "")[:10] == day.isoformat()
                )
                orows = store.query_l0_events(
                    kind="session_overlay",
                    since=day.isoformat(),
                    limit=500,
                )
                overlay_events = sum(
                    1 for r in orows if str(r.get("at") or "")[:10] == day.isoformat()
                )
            except Exception:
                pass

        daily = _load_daily_record(day)
        db_daily = read_session_overlay_daily(day, settings=cfg) if storage_enabled(cfg) else None
        morning_scans = int((daily.get("morning") or {}).get("scan_count") or 0)
        afternoon_scans = int((daily.get("afternoon") or {}).get("scan_count") or 0)
        telemetry_scans = morning_scans + afternoon_scans

        gap = "ok"
        if ok_trade and telemetry_scans == 0:
            gap = "missing_overlay"
        elif intraday_scans > 0 and overlay_events == 0 and storage_enabled(cfg):
            gap = "missing_overlay_events"
        elif intraday_scans > overlay_events and overlay_events > 0:
            gap = "partial_events"

        days_out.append(
            {
                "date": day.isoformat(),
                "intraday_scans_db": intraday_scans,
                "overlay_events_db": overlay_events,
                "telemetry_scan_count": telemetry_scans,
                "day_merged_regime": daily.get("day_merged_regime"),
                "day_threshold_patched": daily.get("day_threshold_patched"),
                "db_file_seen_match": (
                    bool((daily.get("morning") or {}).get("seen"))
                    == bool(((db_daily or {}).get("morning") or {}).get("seen"))
                    if db_daily
                    else None
                ),
                "gap": gap,
            }
        )
        day += timedelta(days=1)

    gaps = [d for d in days_out if d.get("gap") not in ("ok", None)]
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "overlay_stats": overlay_stats,
        "days": days_out,
        "gap_days": len(gaps),
        "status": "ok" if not gaps else "warn",
    }


def cmd_quant(args: argparse.Namespace) -> None:
    settings = load_settings()
    action = args.quant_action

    if action == "doctor":
        from agent_reach.daily_run.quant_chain_doctor import format_quant_chain_doctor, run_quant_chain_doctor

        report = run_quant_chain_doctor(settings=settings)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_quant_chain_doctor(report))
        if report.get("status") == "error":
            sys.exit(1)
        return

    if action == "reconcile":
        week_start = date.fromisoformat(args.week_start) if args.week_start else _default_week_start()
        report = reconcile_quant_week(week_start, settings=settings)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Week {report['week_start']} ~ {report['week_end']} · status={report['status']}")
            stats = report.get("overlay_stats") or {}
            print(
                f"  overlay: quality={stats.get('data_quality')} "
                f"log={stats.get('log_days')}/{stats.get('trading_days_in_range')} "
                f"source={stats.get('source')}"
            )
            for row in report.get("days") or []:
                mark = "✅" if row.get("gap") == "ok" else "⚠️"
                print(
                    f"  {mark} {row['date']} scans={row['telemetry_scan_count']} "
                    f"regime={row.get('day_merged_regime')} gap={row.get('gap')}"
                )
        if report.get("status") != "ok":
            sys.exit(1)
        return

    if action == "repair":
        from agent_reach.daily_run.quant_repair import repair_quant_chain

        report = repair_quant_chain(settings=settings)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            handoff = report.get("close_handoff") or {}
            wo = report.get("week_open") or {}
            repaired = handoff.get("repaired") or []
            if repaired:
                print(f"✅ close handoff seed repaired: {', '.join(repaired)}")
            else:
                print("✅ close handoff seeds: nothing to repair")
            if wo.get("status") == "ok":
                print(
                    f"✅ week_open overlay: {wo.get('regime')} "
                    f"({wo.get('week_start')}~{wo.get('week_end')})"
                )
            elif wo.get("status") == "skipped":
                print(f"✅ week_open: {wo.get('reason')} ({wo.get('week_start')})")
            else:
                print(f"⚠️ week_open: {wo.get('reason')}")
            for err in handoff.get("errors") or []:
                print(f"❌ {err}")
        return

    print(f"Unknown quant action: {action}")
    sys.exit(1)
