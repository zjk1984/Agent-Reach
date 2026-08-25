# -*- coding: utf-8
"""Daily-run storage configuration (SQLite default, Postgres Phase 3)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB_NAME = "daily_run.db"


def storage_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if settings is None:
        from agent_reach.daily_run.settings import load_settings

        settings = load_settings()
    block = dict((settings or {}).get("storage") or {})
    return block


def storage_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    if os.environ.get("AGENT_REACH_STORAGE", "").strip().lower() in ("0", "false", "off", "no"):
        return False
    cfg = storage_settings(settings)
    return bool(cfg.get("enabled", False))


def storage_backend(settings: Optional[dict[str, Any]] = None) -> str:
    cfg = storage_settings(settings)
    backend = str(cfg.get("backend") or "sqlite").strip().lower()
    if backend not in ("sqlite", "postgres"):
        return "sqlite"
    return backend


def sqlite_db_path(settings: Optional[dict[str, Any]] = None) -> Path:
    cfg = storage_settings(settings)
    raw = str(cfg.get("sqlite_path") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".agent-reach" / "daily_run" / _DEFAULT_DB_NAME


def postgres_dsn(settings: Optional[dict[str, Any]] = None) -> str:
    cfg = storage_settings(settings)
    pg = dict(cfg.get("postgres") or {})
    return str(pg.get("dsn") or os.environ.get("AGENT_REACH_STORAGE_DSN") or "").strip()


def distill_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = storage_settings(settings)
    return dict(cfg.get("distill") or {})
