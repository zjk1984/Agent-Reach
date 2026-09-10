# -*- coding: utf-8
"""Atomic JSON checkpoints for long daily-run jobs (DeepEar-style resume)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


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
