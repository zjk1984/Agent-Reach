# -*- coding: utf-8
"""Cache agent-reach doctor results for the trading day."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def doctor_cache_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "cache" / f"doctor_{today_shanghai().isoformat()}.json"


def load_doctor_cache(ttl_seconds: int = 14400) -> Optional[dict[str, Any]]:
    path = doctor_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - float(data.get("ts") or 0) > ttl_seconds:
        return None
    channels = data.get("channels")
    return channels if isinstance(channels, dict) else None


def save_doctor_cache(channels: dict[str, Any]) -> Path:
    path = doctor_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ts": time.time(), "channels": channels}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def doctor_channels_cached(config, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = (settings or {}).get("schedule") or {}
    if cfg.get("doctor_cache", True) is False:
        from agent_reach.daily_run.schedule import _doctor_channels

        return _doctor_channels(config)

    ttl = int(cfg.get("doctor_cache_ttl_seconds", 14400))
    cached = load_doctor_cache(ttl_seconds=ttl)
    if cached is not None:
        return cached

    from agent_reach.doctor import check_all

    channels = check_all(config)
    save_doctor_cache(channels)
    return channels
