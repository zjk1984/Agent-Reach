# -*- coding: utf-8
"""Daily snapshot layer cache — macro/technicals reused across intraday scans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def cache_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "cache"


def daily_cache_path(d: Optional[Any] = None) -> Path:
    day = d.isoformat() if d is not None and hasattr(d, "isoformat") else today_shanghai().isoformat()
    return cache_dir() / f"{day}.json"


def load_daily_cache(d: Optional[Any] = None) -> dict[str, Any]:
    path = daily_cache_path(d)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_daily_cache(data: dict[str, Any], d: Optional[Any] = None) -> Path:
    cache_dir().mkdir(parents=True, exist_ok=True)
    path = daily_cache_path(d)
    existing = load_daily_cache(d)
    existing.update(data)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def last_snapshot_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "last_snapshot.json"


def load_last_snapshot() -> Optional[dict[str, Any]]:
    path = last_snapshot_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
