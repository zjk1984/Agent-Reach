# -*- coding: utf-8
"""Load daily_run_settings.json with optional user override."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "daily_run_settings.json"
_USER_PATH = Path.home() / ".agent-reach" / "daily_run_settings.json"

_settings_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load settings; user override at ~/.agent-reach/daily_run_settings.json wins."""
    if path is not None:
        return _read_json(path)

    active = _USER_PATH if _USER_PATH.exists() else _DEFAULT_PATH
    if not active.exists():
        raise FileNotFoundError(
            f"daily_run settings not found. Expected {_DEFAULT_PATH} or {_USER_PATH}"
        )

    mtime = active.stat().st_mtime
    if (
        _settings_cache["path"] == active
        and _settings_cache["mtime"] == mtime
        and _settings_cache["data"] is not None
    ):
        return deepcopy(_settings_cache["data"])

    data = _read_json(active)
    _settings_cache["path"] = active
    _settings_cache["mtime"] = mtime
    _settings_cache["data"] = data
    return deepcopy(data)


def clear_settings_cache() -> None:
    """Invalidate cached settings (tests)."""
    _settings_cache["path"] = None
    _settings_cache["mtime"] = None
    _settings_cache["data"] = None


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid settings file: {path}")
    return deepcopy(data)
