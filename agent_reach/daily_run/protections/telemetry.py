# -*- coding: utf-8
"""Persist active protection locks into daily overlay_log."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.trade_calendar import today_shanghai

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _log_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "overlay_log"


def _log_path(day) -> Path:
    return _log_dir() / f"{day.isoformat()}.json"


def record_protection_events(
    events: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
    code: str = "",
) -> None:
    if not events:
        return
    day = today_shanghai()
    path = _log_path(day)
    row: dict[str, Any]
    if path.is_file():
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            row = {"date": day.isoformat(), "version": 2}
    else:
        row = {"date": day.isoformat(), "version": 2}

    prot = list(row.get("protections") or [])
    at = datetime.now(_SH_TZ).isoformat()
    for ev in events:
        prot.append({**ev, "at": at, "trigger_code": code or ev.get("code")})
    row["protections"] = prot[-40:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
