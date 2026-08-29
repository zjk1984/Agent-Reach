# -*- coding: utf-8
"""Berkshire integration settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def berkshire_cfg(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings is None:
        from agent_reach.daily_run.settings import load_settings

        settings = load_settings()
    return dict((settings or {}).get("berkshire") or {})


def berkshire_enabled(settings: dict[str, Any] | None = None, *, key: str | None = None) -> bool:
    cfg = berkshire_cfg(settings)
    if cfg.get("enabled", True) is False:
        return False
    if key is None:
        return True
    return cfg.get(key, True) is not False


def thesis_dir(settings: dict[str, Any] | None = None) -> Path:
    cfg = berkshire_cfg(settings)
    raw = cfg.get("thesis_dir") or "~/.agent-reach/daily_run/thesis"
    return Path(str(raw)).expanduser()


def thesis_snapshot_dir(settings: dict[str, Any] | None = None) -> Path:
    return thesis_dir(settings) / "snapshots"
