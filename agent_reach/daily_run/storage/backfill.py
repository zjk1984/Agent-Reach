# -*- coding: utf-8
"""Backfill SQLite store from ~/.agent-reach/daily_run file artifacts."""

from __future__ import annotations

import json
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
        except (json.JSONDecodeError, OSError):
            pass

    return {"backfilled": stats, "status": store.status()}
