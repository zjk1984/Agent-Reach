# -*- coding: utf-8 -*-
"""Load daily_run_settings.json with optional user override."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "daily_run_settings.json"
_USER_PATH = Path.home() / ".agent-reach" / "daily_run_settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load settings; user override at ~/.agent-reach/daily_run_settings.json wins."""
    if path is not None:
        return _read_json(path)

    if _USER_PATH.exists():
        return _read_json(_USER_PATH)
    if _DEFAULT_PATH.exists():
        return _read_json(_DEFAULT_PATH)
    raise FileNotFoundError(
        f"daily_run settings not found. Expected {_DEFAULT_PATH} or {_USER_PATH}"
    )


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid settings file: {path}")
    return deepcopy(data)
