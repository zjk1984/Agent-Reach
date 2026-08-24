# -*- coding: utf-8
"""Bounded JSONL append helper.

Harness audit/diff trails (``refinements.jsonl``, ``apply_audit.jsonl``,
``overlay_diff.jsonl``, ``memory_diff.jsonl``) are pure append-only logs with no
rotation, unlike ``harness_snapshot.py`` which caps snapshot count. Left alone
they grow forever (observed: overlay_diff.jsonl reaching double-digit MB after
a few weeks of cron activity). This module bounds them cheaply: appends are
O(1) as usual, and only once a file crosses ``check_every_bytes`` do we pay the
O(n) cost of truncating it back down to the most recent ``max_lines`` lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MAX_LINES = 2000
DEFAULT_CHECK_EVERY_BYTES = 2_000_000  # 2MB


def append_jsonl_capped(
    path: Path,
    record: dict[str, Any],
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    check_every_bytes: int = DEFAULT_CHECK_EVERY_BYTES,
) -> None:
    """Append ``record`` as one JSON line; truncate to the last ``max_lines``
    lines once the file exceeds ``check_every_bytes`` on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= check_every_bytes:
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return

    tail = lines[-max_lines:]
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text("\n".join(tail) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
