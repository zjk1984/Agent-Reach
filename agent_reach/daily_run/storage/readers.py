# -*- coding: utf-8
"""Read-through facade: prefer SQLite when enabled, JSON files as fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.storage.config import (
    path_under_daily_run_data,
    storage_read_prefer_db,
)


def storage_prefer_db(
    settings: Optional[dict[str, Any]] = None,
    *,
    paths: Optional[list[Path]] = None,
) -> bool:
    if not storage_read_prefer_db(settings):
        return False
    if paths:
        canonical = [p for p in paths if p is not None]
        if canonical and not all(path_under_daily_run_data(p) for p in canonical):
            return False
    return True


def _day_bounds(day: str | date) -> tuple[str, str]:
    if isinstance(day, date):
        ds = day.isoformat()
    else:
        ds = str(day or "")[:10]
    if not ds:
        return "", ""
    next_day = (date.fromisoformat(ds) + timedelta(days=1)).isoformat()
    return ds, next_day


def _date_filter_bounds(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> tuple[str, str]:
    since = start.isoformat() if start else ""
    until = ""
    if end is not None:
        until = (end + timedelta(days=1)).isoformat()
    return since, until


def _get_store(settings: Optional[dict[str, Any]] = None):
    from agent_reach.daily_run.storage import get_store

    return get_store(settings)


def read_trade_ledger_entries(
    *,
    settings: Optional[dict[str, Any]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 5000,
) -> Optional[list[dict[str, Any]]]:
    """Return ledger rows from DB, or None to fall back to jsonl."""
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_trade_ledger_entries", None)
    if not callable(query):
        return None
    since, until = _date_filter_bounds(start, end)
    rows = query(since=since, until=until, limit=limit)
    if not rows:
        return None
    from agent_reach.daily_run.portfolio_manager import dedupe_trade_ledger_entries

    return dedupe_trade_ledger_entries(rows)


def read_daily_pnl_records(
    *,
    settings: Optional[dict[str, Any]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 2000,
) -> Optional[list[dict[str, Any]]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_pnl_history_records", None)
    if not callable(query):
        return None
    since, until = _date_filter_bounds(start, end)
    rows = query(since=since, until=until, limit=limit)
    if not rows:
        return None
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        if start is not None and day < start.isoformat():
            continue
        if end is not None and day > end.isoformat():
            continue
        by_date[day] = row
    return [by_date[d] for d in sorted(by_date)]


def read_latest_portfolio(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_latest_portfolio_snapshot", None)
    if not callable(query):
        return None
    payload = query()
    if not isinstance(payload, dict) or not payload:
        return None
    payload = dict(payload)
    payload.pop("_snapshot_at", None)
    payload.pop("_snapshot_source", None)
    return payload


def read_rules_summary(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    return query(state_key="experience:rules_summary", kind="rules_summary")


def read_experience_atoms(
    *,
    settings: Optional[dict[str, Any]] = None,
    code: str = "",
    since: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return []
    store = _get_store(settings)
    rows: list[dict[str, Any]] = []
    for kind in ("experience_summary", "experience_rule"):
        rows.extend(
            store.query_l1_atoms(kind=kind, code=code, since=since, limit=limit)
        )
    rows.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
    return rows[:limit]


def read_intraday_trade_records_for_day(
    day: str | date,
    *,
    settings: Optional[dict[str, Any]] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return []
    since, until = _day_bounds(day)
    if not since:
        return []
    store = _get_store(settings)
    query_l2 = getattr(store, "query_l2_scenarios", None)
    records: list[dict[str, Any]] = []
    if callable(query_l2):
        for row in query_l2(kind="trade_case", since=since, until=until, limit=limit):
            payload = row.get("payload")
            if isinstance(payload, dict) and payload.get("action"):
                records.append(dict(payload))
                continue
            nested = (payload or {}).get("record") if isinstance(payload, dict) else None
            if isinstance(nested, dict) and nested.get("action"):
                records.append(dict(nested))
    if records:
        records.sort(key=lambda item: str(item.get("as_of") or ""))
        return records
    atoms = store.query_l1_atoms(kind="trade_case", since=since, limit=limit)
    for row in atoms:
        payload = row.get("payload") or {}
        nested = payload.get("record") if isinstance(payload, dict) else None
        if isinstance(nested, dict) and nested.get("action"):
            at = str(nested.get("as_of") or row.get("at") or "")
            if until and at >= until:
                continue
            records.append(dict(nested))
    records.sort(key=lambda item: str(item.get("as_of") or ""))
    return records


def read_intraday_scan_best_for_day(
    day: str | date,
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    if not storage_prefer_db(settings):
        return None
    norm = _normalize_code(code)
    since, until = _day_bounds(day)
    if not since or not norm:
        return None
    store = _get_store(settings)
    best: Optional[tuple[str, dict[str, Any]]] = None
    events = store.query_l0_events(
        kind="intraday_scan",
        since=since,
        until=until,
        limit=500,
        order="asc",
    )
    for event in events:
        payload = event.get("payload") or {}
        if _normalize_code(str(payload.get("code") or "")) != norm:
            continue
        if payload.get("mss_final") is None:
            continue
        as_of = str(payload.get("as_of") or event.get("at") or "")
        if best is None or as_of >= best[0]:
            best = (
                as_of,
                {
                    "code": norm,
                    "name": payload.get("name") or norm,
                    "mss_final": float(payload["mss_final"]),
                    "mss_breakdown": payload.get("mss_breakdown") or {},
                    "verdict": payload.get("verdict"),
                    "close_date": since[:10],
                    "scan_id": payload.get("scan_id"),
                    "as_of": as_of or None,
                    "source": "intraday_scan_db",
                },
            )
    if best:
        return best[1]
    atoms = store.query_l1_atoms(kind="intraday_scan", code=norm, since=since, limit=100)
    for row in atoms:
        payload = row.get("payload") or {}
        mss = payload.get("mss_final")
        if mss is None:
            continue
        as_of = str(row.get("at") or "")
        if until and as_of >= until:
            continue
        if best is None or as_of >= best[0]:
            best = (
                as_of,
                {
                    "code": norm,
                    "name": payload.get("name") or row.get("title") or norm,
                    "mss_final": float(mss),
                    "mss_breakdown": payload.get("mss_breakdown") or {},
                    "verdict": payload.get("verdict"),
                    "close_date": since[:10],
                    "scan_id": payload.get("scan_id"),
                    "as_of": as_of or None,
                    "source": "intraday_scan_db",
                },
            )
    return best[1] if best else None


def read_close_baseline_from_store(
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    day: str | date | None = None,
) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    if not storage_prefer_db(settings):
        return None
    norm = _normalize_code(code)
    store = _get_store(settings)
    query_l2 = getattr(store, "query_l2_scenarios", None)
    if not callable(query_l2):
        return None
    key = f"close/{norm}"
    since = ""
    until = ""
    if day is not None:
        since, until = _day_bounds(day)
    rows = query_l2(
        kind="baseline_close",
        scenario_key=key,
        code=norm,
        since=since,
        until=until,
        limit=5,
    )
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict) and payload.get("mss_final") is not None:
            out = dict(payload)
            out.setdefault("close_date", str(row.get("at") or out.get("close_date") or "")[:10])
            out.setdefault("_baseline_source", "baseline_close_db")
            return out
    return None


def read_harness_state_payload(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    list_entries = getattr(store, "list_harness_entries", None)
    if not callable(list_entries):
        return None
    rows = list_entries()
    if not rows:
        return None
    entries: dict[str, dict[str, Any]] = {}
    updated_at = ""
    for row in rows:
        kind = str(row.get("kind") or "")
        entry_id = str(row.get("entry_id") or "")
        if not kind or not entry_id:
            continue
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            raw = dict(payload)
        else:
            raw = {
                "id": entry_id,
                "title": row.get("title") or entry_id,
                "content": row.get("content") or "",
                "version": row.get("version") or 1,
                "status": row.get("status") or "",
                "updated_at": row.get("updated_at") or "",
            }
        entries.setdefault(kind, {})[entry_id] = raw
        stamp = str(raw.get("updated_at") or row.get("updated_at") or "")
        if stamp >= updated_at:
            updated_at = stamp
    if not entries:
        return None
    return {
        "schema": 2,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "refinements": [],
        "_source": "harness_db",
    }


def read_l2_payload(
    kind: str,
    scenario_key: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query_l2 = getattr(store, "query_l2_scenarios", None)
    if not callable(query_l2):
        return None
    rows = query_l2(kind=kind, scenario_key=scenario_key, limit=1)
    if not rows:
        return None
    payload = rows[0].get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def read_l3_document(
    kind: str,
    doc_key: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    getter = getattr(store, "get_l3_document", None)
    if not callable(getter):
        return None
    return getter(kind, doc_key)


def attach_optimizer_storage_context(
    payload: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    job: str = "optimizer",
    extra_sources: Optional[list[Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.storage.retrieval import attach_storage_retrieval

    sources = [payload]
    if extra_sources:
        sources.extend(extra_sources)
    return attach_storage_retrieval(payload, settings=settings, job=job, extra_sources=sources)


def read_job_run_manifests(
    start: date,
    end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
    job: str = "",
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Return job run manifests from L0 ``job_run`` events."""
    if not storage_prefer_db(settings):
        return []
    since, until = _date_filter_bounds(start, end)
    store = _get_store(settings)
    events = store.query_l0_events(
        kind="job_run",
        since=since,
        until=until,
        limit=limit,
        order="asc",
    )
    records: list[dict[str, Any]] = []
    for event in events:
        manifest = event.get("payload") or {}
        if not isinstance(manifest, dict) or not manifest.get("job"):
            continue
        if job and str(manifest.get("job") or "") != job:
            continue
        day = str(manifest.get("date") or event.get("at") or "")[:10]
        if not day or day < start.isoformat() or day > end.isoformat():
            continue
        record = dict(manifest)
        record["_run_date"] = day
        record["_path"] = str(event.get("source_path") or record.get("_path") or "")
        record["_source"] = "job_run_db"
        records.append(record)
    return records


def read_week_forecast(
    week_start: date | str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if isinstance(week_start, date):
        key = week_start.isoformat()
    else:
        key = str(week_start or "")[:10]
    if not key:
        return None
    payload = read_l2_payload("forecast", key, settings=settings)
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_active_week_forecast(
    as_of: Optional[date] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    from agent_reach.daily_run.trade_calendar import today_shanghai

    target = as_of or today_shanghai()
    store = _get_store(settings)
    query_l2 = getattr(store, "query_l2_scenarios", None)
    if not callable(query_l2):
        return None
    rows = query_l2(kind="forecast", limit=52)
    best: Optional[dict[str, Any]] = None
    best_ws = ""
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        try:
            ws = date.fromisoformat(str(payload.get("week_start") or row.get("scenario_key") or "")[:10])
            we = date.fromisoformat(str(payload.get("week_end") or "")[:10])
        except ValueError:
            continue
        if ws <= target <= we and ws.isoformat() >= best_ws:
            best = dict(payload)
            best_ws = ws.isoformat()
    return best


def read_experience_entries(
    *,
    settings: Optional[dict[str, Any]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return []
    since, until = _date_filter_bounds(start, end)
    store = _get_store(settings)
    events = store.query_l0_events(
        kind="experience",
        since=since,
        until=until,
        limit=max(limit, 1),
        order="desc",
    )
    rows: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        ds = str(payload.get("date") or payload.get("at") or "")[:10]
        if start is not None and ds and ds < start.isoformat():
            continue
        if end is not None and ds and ds > end.isoformat():
            continue
        rows.append(dict(payload))
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("at") or "")), reverse=True)
    return rows[:limit]


def read_capital_events(
    *,
    settings: Optional[dict[str, Any]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return []
    since, until = _date_filter_bounds(start, end)
    store = _get_store(settings)
    events = store.query_l0_events(
        kind="capital_event",
        since=since,
        until=until,
        limit=max(limit, 1),
        order="asc",
    )
    rows: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        ds = str(payload.get("date") or event.get("at") or "")[:10]
        if start is not None and ds and ds < start.isoformat():
            continue
        if end is not None and ds and ds > end.isoformat():
            continue
        rows.append(dict(payload))
    rows.sort(key=lambda row: str(row.get("date") or ""))
    return rows[:limit]


def read_daily_trade_state(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    payload = query(state_key="daily_trade_state", kind="daily_trade_state")
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_rejected_strategies(
    *,
    settings: Optional[dict[str, Any]] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return []
    store = _get_store(settings)
    events = store.query_l0_events(
        kind="rejected_strategy",
        limit=max(limit, 1),
        order="desc",
    )
    rows: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        if isinstance(payload, dict) and payload:
            rows.append(dict(payload))
    return rows[:limit]


def read_runtime_overlay(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    payload = read_l2_payload("runtime_overlay", "effective", settings=settings)
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_job_health(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    payload = query(state_key="job_health", kind="job_health")
    if not isinstance(payload, dict) or not payload:
        return None
    data = dict(payload)
    data.setdefault("jobs", {})
    return data


def read_pnl_target_state(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    payload = query(state_key="pnl_target", kind="pnl_target")
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_last_snapshot(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    payload = query(state_key="last_snapshot", kind="last_snapshot")
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_daily_cache(
    day: str | date,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if isinstance(day, date):
        key = day.isoformat()
    else:
        key = str(day or "")[:10]
    if not key:
        return None
    if not storage_prefer_db(settings):
        return None
    store = _get_store(settings)
    query = getattr(store, "query_l1_state", None)
    if not callable(query):
        return None
    payload = query(state_key=f"daily_cache:{key}", kind="daily_cache")
    return dict(payload) if isinstance(payload, dict) and payload else None


def read_morning_baseline_from_store(
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    if not storage_prefer_db(settings):
        return None
    norm = _normalize_code(code)
    if not norm:
        return None
    store = _get_store(settings)
    query_l2 = getattr(store, "query_l2_scenarios", None)
    if not callable(query_l2):
        return None
    key = f"morning/{norm}"
    rows = query_l2(
        kind="baseline_morning",
        scenario_key=key,
        code=norm,
        limit=5,
    )
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            out = dict(payload)
            out.setdefault("_baseline_source", "baseline_morning_db")
            return out
    return None
