# -*- coding: utf-8
"""Daily-run storage configuration (SQLite default, Postgres Phase 3)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB_NAME = "daily_run.db"


def daily_run_data_root() -> Path:
    return Path.home() / ".agent-reach" / "daily_run"


def path_under_daily_run_data(path: Path) -> bool:
    """True when ``path`` lives under the canonical daily-run data directory."""
    try:
        path.resolve().relative_to(daily_run_data_root().resolve())
        return True
    except ValueError:
        return False


def storage_db_reads_allowed(
    settings: Optional[dict[str, Any]] = None,
    *,
    file_path: Optional[Path] = None,
    explicit_path: bool = False,
) -> bool:
    """Whether read-through should query SQLite before local files."""
    if explicit_path:
        return False
    if not storage_read_prefer_db(settings):
        return False
    if file_path is not None and path_under_daily_run_data(file_path):
        return True
    if settings is not None and storage_enabled(settings):
        return True
    return False


def storage_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if settings is None:
        from agent_reach.daily_run.settings import load_settings

        settings = load_settings()
    block = dict((settings or {}).get("storage") or {})
    return block


def storage_read_prefer_db(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = storage_settings(settings)
    if not storage_enabled(settings):
        return False
    return cfg.get("read_prefer_db", True) is not False


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


def retrieval_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = storage_settings(settings)
    block = dict(cfg.get("retrieval") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "lookback_days": max(1, int(block.get("lookback_days") or 30)),
        "max_codes": max(1, int(block.get("max_codes") or 8)),
        "max_atoms_per_code": max(1, int(block.get("max_atoms_per_code") or 4)),
        "max_trades": max(1, int(block.get("max_trades") or 15)),
        "max_line_chars": max(48, int(block.get("max_line_chars") or 120)),
        "include_trades": block.get("include_trades", True) is not False,
        "atom_kinds": list(
            block.get("atom_kinds")
            or [
                "trade_action",
                "experience_summary",
                "experience_rule",
                "trade_batch",
            ]
        ),
        "llm_jobs": dict(block.get("llm_jobs") or {}),
    }


def prune_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = storage_settings(settings)
    block = dict(cfg.get("prune") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "auto_on_forecast": block.get("auto_on_forecast", True) is not False,
        "runs_keep_days": max(1, int(block.get("runs_keep_days") or 60)),
        "cache_keep_days": max(1, int(block.get("cache_keep_days") or 14)),
        "log_keep_days": max(1, int(block.get("log_keep_days") or 30)),
        "l0_keep_days": max(1, int(block.get("l0_keep_days") or 90)),
        "forecast_keep_days": max(1, int(block.get("forecast_keep_days") or 56)),
        "market_review_keep_days": max(1, int(block.get("market_review_keep_days") or 30)),
        "intraday_keep_days": max(0, int(block.get("intraday_keep_days") or 1)),
        "snapshot_keep": max(3, int(block.get("snapshot_keep") or 20)),
        "vacuum": block.get("vacuum", True) is not False,
    }
