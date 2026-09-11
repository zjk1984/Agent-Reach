# -*- coding: utf-8
"""Run protection plugins and persist overlay telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.protections.iprotection import ProtectionReturn, protections_enabled
from agent_reach.daily_run.protections.max_drawdown_guard import evaluate_max_drawdown_guard
from agent_reach.daily_run.protections.post_sell_cooldown import evaluate_post_sell_cooldown
from agent_reach.daily_run.protections.sector_mss_mismatch import (
    evaluate_sector_mss_mismatch,
    protection_verdict_cap,
)
from agent_reach.daily_run.snapshot_builder import _normalize_code

_SH_TZ = ZoneInfo("Asia/Shanghai")


def evaluate_protections(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    side: str,
    settings: Optional[dict[str, Any]] = None,
    prior_trades: Optional[list[dict[str, Any]]] = None,
    session_scans: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> list[ProtectionReturn]:
    if not protections_enabled(settings):
        return []

    code = str(report.get("code") or "")
    name = str(report.get("name") or code)
    dt = now or datetime.now(_SH_TZ)
    locks: list[ProtectionReturn] = []

    global_lock = evaluate_max_drawdown_guard(
        side=side,
        settings=settings,
        prior_trades=prior_trades,
    )
    if global_lock and global_lock.lock:
        locks.append(global_lock)

    pair_checks = (
        evaluate_post_sell_cooldown(
            code=code,
            name=name,
            side=side,
            settings=settings,
            prior_trades=prior_trades,
            session_scans=session_scans,
            now=dt,
        ),
        evaluate_sector_mss_mismatch(
            snapshot=snapshot,
            report=report,
            side=side,
            settings=settings,
        ),
    )
    for item in pair_checks:
        if item and item.lock:
            locks.append(item)
    return locks


def protection_block_reason(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    side: str,
    settings: Optional[dict[str, Any]] = None,
    prior_trades: Optional[list[dict[str, Any]]] = None,
    session_scans: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Optional[ProtectionReturn]:
    side_l = str(side or "").lower()
    for lock in evaluate_protections(
        snapshot=snapshot,
        report=report,
        side=side_l,
        settings=settings,
        prior_trades=prior_trades,
        session_scans=session_scans,
        now=now,
    ):
        if lock.lock_side in {side_l, "*"}:
            return lock
    return None


def protection_overlay_note(locks: list[ProtectionReturn]) -> str:
    if not locks:
        return ""
    parts = [f"（{lock.reason}）" for lock in locks[:2]]
    return "".join(parts)


def record_protection_hits(
    locks: list[ProtectionReturn],
    *,
    settings: Optional[dict[str, Any]] = None,
    code: str = "",
) -> None:
    if not locks:
        return
    try:
        from agent_reach.daily_run.protections.telemetry import record_protection_events

        record_protection_events(
            [lock.to_dict() for lock in locks],
            settings=settings,
            code=code,
        )
    except Exception:
        pass


__all__ = [
    "evaluate_protections",
    "protection_block_reason",
    "protection_overlay_note",
    "protection_verdict_cap",
    "record_protection_hits",
]
