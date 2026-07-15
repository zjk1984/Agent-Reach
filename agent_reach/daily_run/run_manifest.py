# -*- coding: utf-8
"""Persist daily-run execution manifests for observability."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run")


def runs_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "runs"


def _json_safe(value: Any) -> Any:
    """Coerce manifest payload to JSON-serializable structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


def save_run_manifest(
    job: str,
    payload: dict[str, Any],
    *,
    feishu: Optional[dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
) -> Path:
    """Write structured run record under runs/YYYY-MM-DD/."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = runs_dir() / today
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    path = out_dir / f"{job}_{ts}.json"
    record = {
        "job": job,
        "at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "feishu": feishu,
        "payload": payload,
    }
    path.write_text(
        json.dumps(_json_safe(record), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("daily-run manifest saved: {}", path)
    return path


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
