# -*- coding: utf-8
"""Fallback morning baseline when last_morning.json is missing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_cache import load_last_snapshot


def default_baseline_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "last_morning.json"


def baseline_from_intraday_scans(scans: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not scans:
        return None
    first = scans[0]
    snap: dict[str, Any] = {
        "code": first.get("code"),
        "name": first.get("name"),
        "mss_final": first.get("mss_final"),
        "mss_breakdown": first.get("mss_breakdown"),
        "verdict": first.get("verdict"),
        "as_of": first.get("as_of"),
        "report_type": "premarket_fallback",
        "_baseline_source": "intraday_first_scan",
    }
    if first.get("mss_range"):
        snap["mss_range"] = first.get("mss_range")
    return snap


def load_close_baseline(
    *,
    scans: Optional[list[dict[str, Any]]] = None,
    baseline_path: Optional[Path] = None,
) -> tuple[dict[str, Any], str]:
    """
    Load morning baseline for close verify.

    Priority: last_morning.json → first intraday scan → last_snapshot.json
    """
    import json

    p = baseline_path or default_baseline_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")), "last_morning.json"

    from_scan = baseline_from_intraday_scans(list(scans or []))
    if from_scan:
        return from_scan, "intraday_first_scan"

    last = load_last_snapshot()
    if last:
        fallback = dict(last)
        fallback.setdefault("_baseline_source", "last_snapshot")
        fallback["report_type"] = "premarket_fallback"
        return fallback, "last_snapshot.json"

    raise FileNotFoundError(
        "未找到早盘基线：无 last_morning.json、盘中扫描或 last_snapshot.json"
    )
