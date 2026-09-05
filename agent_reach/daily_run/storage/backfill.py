# -*- coding: utf-8
"""Backfill SQLite store from ~/.agent-reach/daily_run file artifacts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.experience import experience_dir
from agent_reach.daily_run.harness import harness_dir
from agent_reach.daily_run.portfolio_manager import default_ledger_path
from agent_reach.daily_run.snapshot_builder import default_portfolio_path


def _iter_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return []
    rows: list[tuple[int, dict[str, Any]]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append((idx, json.loads(line)))
        except json.JSONDecodeError:
            continue
    return rows


def backfill_from_files(
    *,
    root: Optional[Path] = None,
    force: bool = False,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.storage import get_store, reset_store
    from agent_reach.daily_run.storage.config import sqlite_db_path, storage_backend, storage_enabled

    if not storage_enabled(settings):
        return {"skipped": True, "reason": "storage_disabled"}

    if force and storage_backend(settings) == "sqlite":
        db_path = sqlite_db_path(settings)
        if db_path.exists():
            db_path.unlink()
        reset_store()

    store = get_store(settings)
    base = root or Path.home() / ".agent-reach" / "daily_run"
    stats: dict[str, int] = {}

    ledger = default_ledger_path() if root is None else base / "trade_ledger.jsonl"
    for line_no, row in _iter_jsonl(ledger):
        trade_id = str(row.get("trade_id") or "")
        at = str(row.get("at") or "")
        store.append_l0_event(
            "trade",
            row,
            at=at,
            source_path=str(ledger),
            dedupe_key=f"backfill:trade:{ledger.name}:{line_no}:{trade_id}",
        )
        stats["trade"] = stats.get("trade", 0) + 1

    pf_path = default_portfolio_path() if root is None else base / "portfolio.json"
    if pf_path.exists():
        try:
            portfolio = json.loads(pf_path.read_text(encoding="utf-8"))
            if isinstance(portfolio, dict):
                store.upsert_portfolio(portfolio, source="backfill")
                stats["portfolio"] = 1
        except (json.JSONDecodeError, OSError):
            pass

    exp_path = (experience_dir() if root is None else base / "experience") / "experience.jsonl"
    for line_no, row in _iter_jsonl(exp_path):
        at = str(row.get("at") or row.get("date") or "")
        code = str(row.get("code") or "")
        store.append_l0_event(
            "experience",
            row,
            at=at,
            source_path=str(exp_path),
            dedupe_key=f"backfill:experience:{line_no}:{at}:{code}",
        )
        stats["experience"] = stats.get("experience", 0) + 1

    harness_root = harness_dir() if root is None else base / "harness"
    for name, kind in (
        ("refinements.jsonl", "harness_refinement"),
        ("overlay_diff.jsonl", "harness_overlay_diff"),
        ("memory_diff.jsonl", "harness_memory_diff"),
        ("apply_audit.jsonl", "harness_audit"),
    ):
        path = harness_root / name
        for line_no, row in _iter_jsonl(path):
            at = str(row.get("at") or row.get("created_at") or "")
            store.append_l0_event(
                kind,
                row,
                at=at,
                source_path=str(path),
                dedupe_key=f"backfill:{kind}:{line_no}:{at}",
            )
            stats[kind] = stats.get(kind, 0) + 1
            if kind == "harness_refinement":
                for edit in row.get("edits") or []:
                    if isinstance(edit, dict):
                        store.append_harness_entry_history(
                            kind=str(edit.get("kind") or ""),
                            entry_id=str(edit.get("entry_id") or ""),
                            action=str(edit.get("action") or "update"),
                            payload=edit,
                            at=at,
                        )

    state_path = harness_root / "harness_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                store.sync_harness_state(state)
                stats["harness_state"] = 1
                try:
                    from agent_reach.daily_run.storage.hooks import sync_l3_policy_persona

                    sync_l3_policy_persona(state)
                    stats["policy_persona"] = 1
                except Exception:
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    _backfill_roadmap(store, base, stats)

    return {"backfilled": stats, "status": store.status()}


def _backfill_json_file(store, path: Path, handler, stats: dict[str, int], stat_key: str) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(data, dict):
        handler(data, str(path))
        stats[stat_key] = stats.get(stat_key, 0) + 1


def _backfill_roadmap(store, base: Path, stats: dict[str, int]) -> None:
    from agent_reach.daily_run.storage.hooks import (
        on_baseline,
        on_daily_cache,
        on_forecast,
        on_harness_snapshot,
        on_intraday_state,
        on_job_run,
        on_l1_state,
        on_last_snapshot,
        on_market_review,
        on_rejected_strategy,
        on_rules_summary,
        on_runtime_overlay,
        on_session_overlay_daily,
        on_close_handoff,
        on_week_open_overlay,
        on_skill_changelog,
        on_skill_fragment,
        on_trade_case,
        on_daily_pnl,
        on_capital_event,
    )

    pnl_path = base / "pnl_history.jsonl"
    for line_no, row in _iter_jsonl(pnl_path):
        on_daily_pnl(row, source_path=str(pnl_path))
        stats["pnl_history"] = stats.get("pnl_history", 0) + 1

    cap_path = base / "capital_events.jsonl"
    for line_no, row in _iter_jsonl(cap_path):
        on_capital_event(row, source_path=str(cap_path))
        stats["capital_event"] = stats.get("capital_event", 0) + 1

    for path in (base / "skill_changelog.jsonl",):
        for line_no, row in _iter_jsonl(path):
            on_skill_changelog(row, source_path=str(path))
            stats["skill_changelog"] = stats.get("skill_changelog", 0) + 1

    rej_path = base / "rejected_strategies.jsonl"
    for line_no, row in _iter_jsonl(rej_path):
        on_rejected_strategy(row, source_path=str(rej_path))
        stats["rejected_strategy"] = stats.get("rejected_strategy", 0) + 1

    runs_root = base / "runs"
    if runs_root.exists():
        for path in sorted(runs_root.rglob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_job_run(row, source_path=str(path))
                stats["job_run"] = stats.get("job_run", 0) + 1

    intraday_root = base / "intraday"
    if intraday_root.exists():
        for path in sorted(intraday_root.glob("*.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(state, dict):
                code = path.stem
                on_intraday_state(state, code=code, source_path=str(path))
                stats["intraday_state"] = stats.get("intraday_state", 0) + 1
                for scan in state.get("scans") or []:
                    if isinstance(scan, dict):
                        at = str(scan.get("as_of") or "")
                        scan_id = str(scan.get("scan_id") or "")
                        store.append_l0_event(
                            "intraday_scan",
                            scan,
                            at=at,
                            source_path=str(path),
                            dedupe_key=f"backfill:intraday_scan:{code}:{scan_id}:{at}",
                        )
                        stats["intraday_scan"] = stats.get("intraday_scan", 0) + 1

    _backfill_json_file(
        store,
        base / "daily_trade_state.json",
        lambda d, p: on_l1_state("daily_trade_state", "daily_trade_state", d),
        stats,
        "daily_trade_state",
    )
    _backfill_json_file(
        store,
        base / "job_health.json",
        lambda d, p: on_l1_state("job_health", "job_health", d),
        stats,
        "job_health",
    )
    _backfill_json_file(
        store,
        base / "pnl_target.json",
        lambda d, p: on_l1_state("pnl_target", "pnl_target", d),
        stats,
        "pnl_target",
    )
    rules_path = base / "experience" / "rules_summary.json"
    _backfill_json_file(
        store,
        rules_path,
        lambda d, p: on_rules_summary(d, source_path=p),
        stats,
        "rules_summary",
    )

    overlay_path = base / "harness" / "last_runtime_overlay.json"
    _backfill_json_file(
        store,
        overlay_path,
        lambda d, p: on_runtime_overlay(d, source_path=p),
        stats,
        "runtime_overlay",
    )

    _backfill_json_file(
        store,
        base / "last_snapshot.json",
        lambda d, p: on_last_snapshot(d, source_path=p),
        stats,
        "last_snapshot",
    )

    cache_root = base / "cache"
    if cache_root.exists():
        for path in sorted(cache_root.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_daily_cache(row, day=path.stem, source_path=str(path))
                stats["daily_cache"] = stats.get("daily_cache", 0) + 1

    for kind_dir, kind in (("morning", "morning"), ("close", "close")):
        bdir = base / "baselines" / kind_dir
        if not bdir.exists():
            continue
        for path in sorted(bdir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_baseline(kind, path.stem, row, source_path=str(path))
                stats[f"baseline_{kind}"] = stats.get(f"baseline_{kind}", 0) + 1

    mdir = base / "market_review"
    if mdir.exists():
        for path in sorted(mdir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_market_review(row, review_date=path.stem, source_path=str(path))
                stats["market_review"] = stats.get("market_review", 0) + 1

    fdir = base / "forecasts"
    if fdir.exists():
        for path in sorted(fdir.glob("*.json")):
            if path.name == "calibration.json":
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(row, dict):
                        store.upsert_l2_scenario(
                            "forecast_calibration",
                            "calibration",
                            row,
                            source_path=str(path),
                            dedupe_key="l2:forecast_calibration",
                        )
                        stats["forecast_calibration"] = 1
                except (json.JSONDecodeError, OSError):
                    pass
                continue
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_forecast(row, source_path=str(path))
                stats["forecast"] = stats.get("forecast", 0) + 1

    snap_dir = base / "harness" / "snapshots"
    if snap_dir.exists():
        for path in sorted(snap_dir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_harness_snapshot(row, snapshot_path=str(path))
                stats["harness_snapshot"] = stats.get("harness_snapshot", 0) + 1

    cases_root = base / "memory" / "cases"
    if cases_root.exists():
        for case_dir in sorted(cases_root.iterdir()):
            if not case_dir.is_dir():
                continue
            detail = case_dir / "detail.json"
            if not detail.exists():
                continue
            try:
                rec = json.loads(detail.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            abstract = ""
            overview = ""
            for name, var in ((".abstract.md", "abstract"), (".overview.md", "overview")):
                p = case_dir / name
                if p.exists():
                    text = p.read_text(encoding="utf-8")
                    if var == "abstract":
                        abstract = text
                    else:
                        overview = text
            on_trade_case(case_dir.name, rec, abstract=abstract, overview=overview, source_path=str(detail))
            stats["trade_case"] = stats.get("trade_case", 0) + 1

    skill_dir = base / "skill"
    for name in ("playbook.md", "experience_latest.md"):
        path = skill_dir / name
        if path.exists():
            on_skill_fragment(name.replace(".md", ""), path.read_text(encoding="utf-8"), source_path=str(path))
            stats["skill_doc"] = stats.get("skill_doc", 0) + 1

    overlay_log = base / "overlay_log"
    if overlay_log.is_dir():
        from agent_reach.daily_run.overlay_telemetry import _coerce_v2_record

        for path in sorted(overlay_log.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(row, dict):
                continue
            day_s = path.stem
            daily = _coerce_v2_record(row, date.fromisoformat(day_s))
            on_session_overlay_daily(day_s, daily, source_path=str(path))
            stats["session_overlay_daily"] = stats.get("session_overlay_daily", 0) + 1

    handoff_dir = base / "handoff"
    if handoff_dir.is_dir():
        for path in sorted(handoff_dir.glob("close_*.json")):
            if path.name == "last_close_handoff.json":
                continue
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_close_handoff(row, source_path=str(path))
                stats["close_handoff"] = stats.get("close_handoff", 0) + 1
        for path in sorted(handoff_dir.glob("week_open_*.json")):
            if path.name == "last_week_open_overlay.json":
                continue
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(row, dict):
                on_week_open_overlay(row, source_path=str(path))
                stats["week_open_overlay"] = stats.get("week_open_overlay", 0) + 1
