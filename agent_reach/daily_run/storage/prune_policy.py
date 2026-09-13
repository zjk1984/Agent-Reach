# -*- coding: utf-8
"""Safe retention policy for daily_run.db and companion files."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

# L0 kinds that must never be deleted by automated prune (even when distilled).
PROTECTED_L0_KINDS: tuple[str, ...] = (
    "trade",
    "pnl_history",
    "capital_event",
    "portfolio",
    "rejected_strategy",
)

# L0 kinds eligible for deletion once distilled and older than l0_keep_days.
DEFAULT_PRUNE_L0_KINDS: tuple[str, ...] = (
    "job_run",
    "harness_overlay_diff",
    "harness_memory_diff",
    "harness_audit",
    "harness_refinement",
    "intraday_scan",
    "intraday_state",
    "experience",
    "skill_changelog",
    "session_overlay",
    "daily_trade_state",
)

# High-volume L1 atoms safe to trim (summary already in harness_state / L2).
DEFAULT_PRUNE_L1_KINDS: tuple[str, ...] = (
    "harness_overlay_diff",
    "harness_memory_diff",
    "harness_audit",
)

PROTECTED_L1_KINDS: tuple[str, ...] = (
    "trade_action",
    "trade_batch",
    "trade_case",
    "experience_summary",
    "experience_rule",
    "portfolio_snapshot",
    "job_run",
)

# L2 rows that must never be deleted by automated prune.
PROTECTED_L2_KINDS: tuple[str, ...] = (
    "runtime_overlay",
    "forecast_calibration",
)

DEFAULT_L2_PRUNE_KINDS: tuple[str, ...] = (
    "harness_snapshot",
    "baseline_morning",
    "baseline_close",
    "intraday_state",
    "market_review",
    "technical_watch",
    "close_handoff",
    "week_open_overlay",
    "forecast",
    "trade_case",
)

_STAMP_PREFIX_RE = re.compile(r"^(\d{8})T")


def _parse_iso_date(value: str) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _row_event_date(row: dict[str, Any]) -> Optional[date]:
    for candidate in (
        row.get("at"),
        row.get("scenario_key"),
        (row.get("payload") or {}).get("saved_at"),
        (row.get("payload") or {}).get("close_date"),
        (row.get("payload") or {}).get("week_start"),
        (row.get("payload") or {}).get("date"),
    ):
        parsed = _parse_iso_date(str(candidate or ""))
        if parsed is not None:
            return parsed
    scenario_key = str(row.get("scenario_key") or "")
    match = _STAMP_PREFIX_RE.match(scenario_key)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            return None
    return None


def active_trading_week_start(*, settings: Optional[dict[str, Any]] = None) -> date:
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.week_forecast import next_trading_week_range

    mon, _fri = next_trading_week_range(today_shanghai())
    return mon


def protected_forecast_keys(
    rows: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> set[str]:
    from agent_reach.daily_run.trade_calendar import today_shanghai

    today = today_shanghai()
    active_mon = active_trading_week_start(settings=settings).isoformat()
    protected = {active_mon}
    for row in rows:
        if str(row.get("kind") or "") != "forecast":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        ws = _parse_iso_date(str(payload.get("week_start") or row.get("scenario_key") or ""))
        we = _parse_iso_date(str(payload.get("week_end") or ""))
        if ws is None:
            continue
        if we is None or ws <= today <= we:
            protected.add(str(row.get("scenario_key") or ws.isoformat()))
    return protected


def protected_week_open_keys(*, settings: Optional[dict[str, Any]] = None) -> set[str]:
    mon = active_trading_week_start(settings=settings)
    return {mon.isoformat()}


def l2_kind_keep_days(kind: str, cfg: dict[str, Any]) -> int:
    if kind == "harness_snapshot":
        return max(1, int(cfg.get("harness_snapshot_keep_days") or 14))
    if kind == "close_handoff":
        return max(1, int(cfg.get("close_handoff_keep_days") or 15))
    return max(1, int(cfg.get("l2_keep_days") or 45))


def is_protected_l2_row(
    row: dict[str, Any],
    *,
    cfg: dict[str, Any],
    protected_forecast: set[str],
    protected_week_open: set[str],
) -> bool:
    kind = str(row.get("kind") or "")
    if kind in PROTECTED_L2_KINDS:
        if kind == "runtime_overlay":
            return str(row.get("scenario_key") or "") == "effective"
        return True
    if kind == "forecast":
        key = str(row.get("scenario_key") or "")
        if key in protected_forecast:
            return True
    if kind == "week_open_overlay":
        key = str(row.get("scenario_key") or "")
        if key in protected_week_open:
            return True
    return False


def l2_row_is_stale(
    row: dict[str, Any],
    *,
    cfg: dict[str, Any],
    now: Optional[datetime] = None,
) -> bool:
    kind = str(row.get("kind") or "")
    event_day = _row_event_date(row)
    if event_day is None:
        return False
    anchor = now or datetime.now(timezone.utc)
    keep_days = l2_kind_keep_days(kind, cfg)
    cutoff_day = anchor.date() - timedelta(days=keep_days)
    return event_day < cutoff_day


def effective_prune_l2_kinds(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    if cfg.get("l2_prune_enabled") is False:
        return []
    raw = list(cfg.get("prune_l2_kinds") or DEFAULT_L2_PRUNE_KINDS)
    protected = set(cfg.get("protected_l2_kinds") or PROTECTED_L2_KINDS)
    return [k for k in raw if k not in protected]


def effective_prune_l0_kinds(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    raw = list(cfg.get("prune_l0_kinds") or DEFAULT_PRUNE_L0_KINDS)
    protected = set(cfg.get("protected_l0_kinds") or PROTECTED_L0_KINDS)
    return [k for k in raw if k not in protected]


def effective_prune_l1_kinds(settings: Optional[dict[str, Any]] = None) -> list[str]:
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    if cfg.get("l1_prune_enabled") is False:
        return []
    raw = list(cfg.get("prune_l1_kinds") or DEFAULT_PRUNE_L1_KINDS)
    protected = set(cfg.get("protected_l1_kinds") or PROTECTED_L1_KINDS)
    return [k for k in raw if k not in protected]
