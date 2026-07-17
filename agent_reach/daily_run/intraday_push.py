# -*- coding: utf-8
"""Feishu push policy for intraday scans."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.intraday import MAX_SCANS


def should_push_intraday(
    scan_id: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    trade_happened: bool = False,
    scan_count: int = 0,
) -> bool:
    """
    Decide whether to push Feishu for this intraday scan.

    Modes (schedule.intraday_push_mode):
      - all: every scan (default legacy)
      - smart: S1, S2, last scan, or when trade evaluated
      - trade_only: only when trade_happened
    """
    cfg = (settings or {}).get("schedule") or {}
    mode = str(cfg.get("intraday_push_mode", "smart")).lower()
    milestones = cfg.get("intraday_push_milestones") or ["S1", "S2", "S3", "S15"]

    if mode == "all":
        return True
    if mode == "trade_only":
        return trade_happened
    if trade_happened:
        return True
    if scan_id in milestones:
        return True
    if scan_count >= MAX_SCANS:
        return True
    return False
