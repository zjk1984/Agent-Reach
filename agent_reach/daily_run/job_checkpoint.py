# -*- coding: utf-8
"""Per-job step checkpoints for resumable long runs (OpenStock Inngest step pattern)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def checkpoint_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "checkpoints"


def checkpoint_path(job: str, day: Optional[str] = None) -> Path:
    d = day or today_shanghai().isoformat()
    return checkpoint_dir() / f"{job}_{d}.json"


def load_checkpoint(job: str, day: Optional[str] = None) -> dict[str, Any]:
    path = checkpoint_path(job, day)
    if not path.exists():
        return {"job": job, "date": day or today_shanghai().isoformat(), "steps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"job": job, "date": day or today_shanghai().isoformat(), "steps": {}}
    if not isinstance(data, dict):
        return {"job": job, "date": day or today_shanghai().isoformat(), "steps": {}}
    data.setdefault("steps", {})
    return data


def save_checkpoint(job: str, data: dict[str, Any], day: Optional[str] = None) -> Path:
    path = checkpoint_path(job, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["job"] = job
    payload["date"] = day or today_shanghai().isoformat()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def is_step_done(job: str, step: str, day: Optional[str] = None) -> bool:
    data = load_checkpoint(job, day)
    step_row = (data.get("steps") or {}).get(step) or {}
    return step_row.get("status") == "done"


def mark_step_done(
    job: str,
    step: str,
    *,
    summary: Optional[dict[str, Any]] = None,
    day: Optional[str] = None,
) -> None:
    data = load_checkpoint(job, day)
    steps = dict(data.get("steps") or {})
    steps[step] = {
        "status": "done",
        "at": datetime.now(timezone.utc).isoformat(),
        "summary": summary or {},
    }
    data["steps"] = steps
    save_checkpoint(job, data, day=day)


def clear_checkpoint(job: str, day: Optional[str] = None) -> None:
    path = checkpoint_path(job, day)
    if path.exists():
        path.unlink()


def list_done_steps(job: str, day: Optional[str] = None) -> set[str]:
    data = load_checkpoint(job, day)
    steps = data.get("steps") or {}
    return {name for name, row in steps.items() if isinstance(row, dict) and row.get("status") == "done"}
