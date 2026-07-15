# -*- coding: utf-8
"""Persist Saturday weekly digest for reuse."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def digest_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "weekly_digest.json"


def save_weekly_digest(report: dict[str, Any], *, week_end: Optional[str] = None) -> Path:
    path = digest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "saved_at": today_shanghai().isoformat(),
        "week_end": week_end or report.get("week_end"),
        "hot_sectors": report.get("hot_sectors") or [],
        "sector_research": report.get("sector_research") or [],
        "sector_groups": report.get("sector_groups") or {},
        "skill_learning": report.get("skill_learning") or [],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
