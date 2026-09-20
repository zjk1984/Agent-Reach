# -*- coding: utf-8
"""Atomic JSON checkpoints for long daily-run jobs (DeepEar-style resume).

Also provides per-day step checkpoints for resumable close runs (OpenStock pattern).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def _sanitize_scope_key(scope_key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(scope_key or "default"))[:96]


def checkpoint_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    cfg = dict((settings or {}).get("job_checkpoint") or {})
    raw = str(cfg.get("dir") or "~/.agent-reach/daily_run/cache").strip()
    return Path(os.path.expanduser(raw))


def checkpoint_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = dict((settings or {}).get("job_checkpoint") or {})
    return cfg.get("enabled", True) is not False


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


@dataclass
class JobCheckpoint:
    job: str
    scope_key: str
    base_dir: Path

    @classmethod
    def for_job(
        cls,
        job: str,
        scope_key: str,
        *,
        settings: Optional[dict[str, Any]] = None,
    ) -> JobCheckpoint:
        return cls(job=job, scope_key=scope_key, base_dir=checkpoint_dir(settings))

    @property
    def path(self) -> Path:
        safe_job = _sanitize_scope_key(self.job)
        safe_scope = _sanitize_scope_key(self.scope_key)
        return self.base_dir / f"{safe_job}_{safe_scope}.json"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, Any]:
        if not self.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, data: dict[str, Any]) -> Path:
        content = json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n"
        _atomic_write_text(self.path, content)
        return self.path


# --- Per-day step checkpoints (close job resume) ---


def step_checkpoint_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "checkpoints"


def checkpoint_path(job: str, day: Optional[str] = None) -> Path:
    d = day or today_shanghai().isoformat()
    return step_checkpoint_dir() / f"{job}_{d}.json"


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
