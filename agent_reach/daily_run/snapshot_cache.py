# -*- coding: utf-8
"""Daily snapshot layer cache — macro/technicals reused across intraday scans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai

_CACHE_IO_LOCK = __import__("threading").Lock()


def cache_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "cache"


def _cache_day(d: Optional[Any] = None) -> str:
    if d is not None and hasattr(d, "isoformat"):
        return d.isoformat()
    return today_shanghai().isoformat()


def daily_cache_path(d: Optional[Any] = None) -> Path:
    return cache_dir() / f"{_cache_day(d)}.json"


def load_daily_cache(d: Optional[Any] = None) -> dict[str, Any]:
    path = daily_cache_path(d)
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_daily_cache

        if storage_db_reads_allowed(None, file_path=path):
            from agent_reach.daily_run.settings import load_settings

            db_cache = read_daily_cache(_cache_day(d), settings=load_settings())
            if isinstance(db_cache, dict) and db_cache:
                return db_cache
    except Exception:
        pass
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


_TECHNICAL_FIELDS = ("ma20", "ma5", "position_20d", "volume_ratio")


def merge_technicals(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge per-symbol technical fields; never wipe prior values with empty updates."""
    merged = {code: dict(fields) for code, fields in existing.items() if isinstance(fields, dict)}
    for code, fields in incoming.items():
        if not isinstance(fields, dict):
            continue
        patch = {k: v for k, v in fields.items() if k in _TECHNICAL_FIELDS and v is not None}
        if not patch:
            continue
        prev = merged.get(code)
        if isinstance(prev, dict):
            merged[code] = {**prev, **patch}
        else:
            merged[code] = patch
    return merged


def save_daily_cache(data: dict[str, Any], d: Optional[Any] = None) -> Path:
    with _CACHE_IO_LOCK:
        cache_dir().mkdir(parents=True, exist_ok=True)
        path = daily_cache_path(d)
        existing = load_daily_cache(d)
        payload = dict(data)
        incoming_technicals = payload.pop("technicals", None)
        if isinstance(incoming_technicals, dict):
            existing["technicals"] = merge_technicals(
                existing.get("technicals") or {},
                incoming_technicals,
            )
        existing.update(payload)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            from agent_reach.daily_run.storage.hooks import on_daily_cache

            on_daily_cache(existing, day=_cache_day(d), source_path=str(path))
        except Exception:
            pass
        return path


def last_snapshot_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "last_snapshot.json"


def load_last_snapshot() -> Optional[dict[str, Any]]:
    path = last_snapshot_path()
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_last_snapshot

        if storage_db_reads_allowed(None, file_path=path):
            from agent_reach.daily_run.settings import load_settings

            db_snap = read_last_snapshot(settings=load_settings())
            if isinstance(db_snap, dict) and db_snap:
                return db_snap
    except Exception:
        pass
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_last_snapshot(data: dict[str, Any], *, path: Optional[Path] = None) -> Path:
    p = path or last_snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from agent_reach.daily_run.storage.hooks import on_last_snapshot

        on_last_snapshot(data, source_path=str(p))
    except Exception:
        pass
    return p
