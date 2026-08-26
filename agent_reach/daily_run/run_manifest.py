# -*- coding: utf-8
"""Persist daily-run execution manifests for observability."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.trade_calendar import today_shanghai

_SH_TZ = ZoneInfo("Asia/Shanghai")

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run")


def runs_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "runs"


def has_job_manifest_today(job: str, *, require_feishu: bool = False) -> bool:
    """True if job already recorded under today's Shanghai date folder."""
    today = today_shanghai()
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_job_run_manifests

        if storage_db_reads_allowed(None, file_path=runs_dir()):
            for record in read_job_run_manifests(today, today):
                if str(record.get("job") or "") != job:
                    continue
                payload = record.get("payload") or {}
                if payload.get("skipped"):
                    continue
                if require_feishu:
                    feishu = record.get("feishu")
                    if not feishu:
                        continue
                return True
    except Exception:
        pass
    out_dir = runs_dir() / today.isoformat()
    if not out_dir.exists():
        return False
    for path in sorted(out_dir.glob(f"{job}_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        payload = data.get("payload") or {}
        if payload.get("skipped"):
            continue
        if require_feishu:
            feishu = data.get("feishu")
            if not feishu:
                continue
        return True
    return False


def _json_safe(value: Any) -> Any:
    """Recursively convert dataclasses / nested results into JSON-serializable data."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return value


def _manifest_shanghai_now() -> datetime:
    return datetime.now(_SH_TZ)


def save_run_manifest(
    job: str,
    payload: dict[str, Any],
    *,
    feishu: Optional[dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
) -> Path:
    """Write structured run record under runs/YYYY-MM-DD/ (Asia/Shanghai trading date)."""
    sh_now = _manifest_shanghai_now()
    today = today_shanghai().isoformat()
    out_dir = runs_dir() / today
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = sh_now.strftime("%H%M%S")
    path = out_dir / f"{job}_{ts}.json"
    record = {
        "job": job,
        "date": today,
        "at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "feishu": feishu,
        "payload": payload,
    }
    path.write_text(
        json.dumps(_json_safe(record), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from agent_reach.daily_run.storage.hooks import on_job_run

        on_job_run(record, source_path=str(path))
    except Exception:
        pass
    logger.info("daily-run manifest saved: {}", path)
    return path


def load_run_manifests_for_range(
    start: date,
    end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Load run manifests for a date range (DB first when enabled, else runs/*.json)."""
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_job_run_manifests

        if storage_db_reads_allowed(settings, file_path=runs_dir()):
            db_rows = read_job_run_manifests(start, end, settings=settings)
            if db_rows:
                return db_rows
    except Exception:
        pass

    records: list[dict[str, Any]] = []
    root = runs_dir()
    if not root.exists():
        return records
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        for path in sorted(day_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            record["_run_date"] = day.isoformat()
            record["_path"] = str(path)
            records.append(record)
    return records


class StepTimer:
    """Context manager for step timing + logging."""

    def __init__(self, step: str):
        self.step = step
        self.start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> StepTimer:
        self.start = time.perf_counter()
        logger.info("daily-run step start: {}", self.step)
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000
        logger.info("daily-run step done: {} ({:.0f}ms)", self.step, self.elapsed_ms)
