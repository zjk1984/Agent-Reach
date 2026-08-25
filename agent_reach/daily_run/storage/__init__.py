# -*- coding: utf-8
"""Daily-run database persistence (SQLite Phase 1, distill Phase 2, Postgres Phase 3)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.storage.base import DailyRunStore
from agent_reach.daily_run.storage.config import (
    postgres_dsn,
    sqlite_db_path,
    storage_backend,
    storage_enabled,
    storage_settings,
)

_store: DailyRunStore | None = None
_store_key: str | None = None


def get_store(settings: Optional[dict[str, Any]] = None) -> DailyRunStore:
    global _store, _store_key
    backend = storage_backend(settings)
    if backend == "postgres":
        key = f"postgres:{postgres_dsn(settings)}"
    else:
        key = f"sqlite:{sqlite_db_path(settings)}"
    if _store is None or _store_key != key:
        if backend == "postgres":
            from agent_reach.daily_run.storage.postgres_store import open_postgres_store

            pg = dict(storage_settings(settings).get("postgres") or {})
            _store = open_postgres_store(
                postgres_dsn(settings),
                schema=str(pg.get("schema") or "daily_run"),
            )
        else:
            from agent_reach.daily_run.storage.sqlite_store import open_sqlite_store

            _store = open_sqlite_store(sqlite_db_path(settings))
        _store_key = key
    return _store


def reset_store() -> None:
    global _store, _store_key
    _store = None
    _store_key = None


__all__ = [
    "DailyRunStore",
    "get_store",
    "reset_store",
    "storage_backend",
    "storage_enabled",
    "storage_settings",
]
