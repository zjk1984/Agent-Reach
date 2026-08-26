# -*- coding: utf-8 -*-
"""Rejected strategy guardrails (DSH rejected Agent Notes style)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REJECTED_PATH = Path.home() / ".agent-reach" / "daily_run" / "rejected_strategies.jsonl"
_ARCHIVE_PATH = _REJECTED_PATH.parent / "rejected_strategies_archive.jsonl"


def rejected_path() -> Path:
    return _REJECTED_PATH


def archive_path() -> Path:
    return _ARCHIVE_PATH


def _normalize_title(title: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", str(title or "").lower())
    return raw[:64]


def _rejected_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = dict((settings or {}).get("rejected_strategies") or {})
    return {
        "harness_evolve": cfg.get("harness_evolve", True),
        "weekly_refresh": cfg.get("weekly_refresh", True),
        "active_week_only": cfg.get("active_week_only", True),
        "archive_expired": cfg.get("archive_expired", True),
        "auto_add_from_weekly": cfg.get("auto_add_from_weekly", True),
    }


def _parse_iso_date(raw: str) -> Optional[date]:
    text = str(raw or "")[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _record_week_bounds(row: dict[str, Any], as_of: Optional[date] = None) -> tuple[str, str]:
    ws = str(row.get("week_start") or "")[:10]
    we = str(row.get("week_end") or "")[:10]
    if ws and we:
        return ws, we
    created = _parse_iso_date(str(row.get("created_at") or ""))
    if created is not None:
        from agent_reach.daily_run.weekly_report import trading_week_range

        monday, friday = trading_week_range(created)
        return monday.isoformat(), friday.isoformat()
    from agent_reach.daily_run.weekly_report import trading_week_range

    monday, friday = trading_week_range(as_of)
    return monday.isoformat(), friday.isoformat()


def _record_in_week(
    row: dict[str, Any],
    week_start: date,
    week_end: date,
    *,
    as_of: Optional[date] = None,
) -> bool:
    ws_s, we_s = _record_week_bounds(row, as_of)
    ws = _parse_iso_date(ws_s)
    we = _parse_iso_date(we_s)
    if ws is None or we is None:
        return False
    return ws == week_start and we == week_end


def load_rejected_records(*, limit: int = 200, settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_rejected_strategies

        if storage_db_reads_allowed(settings, file_path=_REJECTED_PATH):
            from agent_reach.daily_run.settings import load_settings

            rows = read_rejected_strategies(settings=load_settings(), limit=limit)
            if rows:
                return rows[-limit:]
    except Exception:
        pass
    if not _REJECTED_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in _REJECTED_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-limit:]


def load_active_rejected_records(
    *,
    as_of: Optional[date] = None,
    limit: int = 200,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    cfg = _rejected_cfg(settings)
    rows = load_rejected_records(limit=limit, settings=settings)
    if not cfg.get("active_week_only", True):
        return rows
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.weekly_report import trading_week_range

    ref = as_of or today_shanghai()
    week_start, week_end = trading_week_range(ref)
    active = [row for row in rows if _record_in_week(row, week_start, week_end, as_of=ref)]
    return active[-limit:]


def rejected_title_keys(settings: Optional[dict[str, Any]] = None) -> set[str]:
    keys: set[str] = set()
    for row in load_active_rejected_records(settings=settings):
        key = _normalize_title(str(row.get("title") or ""))
        if key:
            keys.add(key)
    return keys


def is_rejected_title(title: str, settings: Optional[dict[str, Any]] = None) -> bool:
    key = _normalize_title(title)
    return bool(key) and key in rejected_title_keys(settings)


_BUY_BLOCK_PHRASES: tuple[str, ...] = (
    "接飞刀",
    "加大仓位",
    "激进建仓",
    "满仓进攻",
    "逆势加仓",
)


def trade_blocked_by_rejected(
    action: str,
    *,
    code: str = "",
    name: str = "",
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return rejected strategy title if trade action should be blocked."""
    harness_cfg = dict((settings or {}).get("harness") or {})
    if harness_cfg.get("runtime_rejected_guard", True) is False:
        return None

    action = str(action or "").lower()
    if action != "buy":
        return None

    for label in (name, code):
        if label and is_rejected_title(str(label), settings=settings):
            return str(label)

    for row in load_active_rejected_records(settings=settings):
        title = str(row.get("title") or "")
        reason = str(row.get("reason") or "")
        blob = f"{title} {reason}"
        if any(p in blob for p in _BUY_BLOCK_PHRASES):
            return title or reason
    return None


def _next_id(existing: list[dict[str, Any]]) -> str:
    max_n = 0
    for row in existing:
        raw = str(row.get("id") or "")
        match = re.search(r"(\d+)$", raw)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"rej_{max_n + 1:04d}"


def _find_same_week_title(
    title: str,
    *,
    week_start: str,
    week_end: str,
    rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    key = _normalize_title(title)
    if not key:
        return None
    for row in rows:
        if _normalize_title(str(row.get("title") or "")) != key:
            continue
        if str(row.get("week_start") or "")[:10] == week_start[:10] and str(row.get("week_end") or "")[:10] == week_end[:10]:
            return row
    return None


def _write_rejected_records(rows: list[dict[str, Any]]) -> None:
    _REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REJECTED_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_archive_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    _ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    archived_at = datetime.now(timezone.utc).isoformat()
    with open(_ARCHIVE_PATH, "a", encoding="utf-8") as f:
        for row in rows:
            payload = dict(row)
            payload.setdefault("archived_at", archived_at)
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return len(rows)


def _dedupe_candidates(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for title, reason in candidates:
        key = _normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((title.strip(), reason.strip()))
    return out


def _candidates_from_weekly_report(report: dict[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    buy = report.get("buy_rules_whatif") or {}
    if not buy.get("skipped"):
        for row in buy.get("rows") or []:
            actual = int(row.get("actual_bought") or 0)
            hypo = int(row.get("hypothetical_bought") or 0)
            block = str(row.get("block_reason") or "").strip()
            if actual <= 0 or actual <= hypo:
                continue
            name = str(row.get("name") or row.get("code") or "").strip()
            blob = f"{block} {name}"
            if any(p in blob for p in _BUY_BLOCK_PHRASES):
                if "接飞刀" in blob:
                    title = "禁止接飞刀追涨"
                elif name:
                    title = f"禁止{name}逆势加仓"
                else:
                    title = "禁止逆势加仓"
                reason = block or f"本周基准多买 {actual - hypo} 股（自进化阻断）"
                candidates.append((title, reason))

        pnl_pct = report.get("weekly_pnl_pct")
        delta = float(buy.get("buy_notional_delta") or 0)
        if pnl_pct is not None and float(pnl_pct) < 0 and delta <= -5000:
            candidates.append(
                (
                    "禁止接飞刀追涨",
                    f"本周亏损 {float(pnl_pct):+.2f}% 且基准买入超自进化 ¥{abs(delta):,.0f}",
                )
            )

    macro = report.get("macro_signals") or {}
    verdict = str(macro.get("verdict") or macro.get("macro_verdict") or "")
    pnl_pct = report.get("weekly_pnl_pct")
    if pnl_pct is not None and float(pnl_pct) < 0 and ("回避" in verdict or macro.get("macro_veto")):
        candidates.append(("禁止接飞刀追涨", "宏观回避期逆势加仓已证伪"))

    return _dedupe_candidates(candidates)


def add_rejected_strategy(
    title: str,
    reason: str,
    *,
    week_start: str = "",
    week_end: str = "",
    source: str = "weekly",
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.weekly_report import trading_week_range

    if not week_start or not week_end:
        monday, friday = trading_week_range()
        week_start = week_start or monday.isoformat()
        week_end = week_end or friday.isoformat()

    existing = load_rejected_records(settings=settings)
    dup = _find_same_week_title(title, week_start=week_start, week_end=week_end, rows=existing)
    if dup:
        return dup

    record = {
        "id": _next_id(existing),
        "title": str(title).strip(),
        "reason": str(reason).strip(),
        "week_start": week_start,
        "week_end": week_end,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REJECTED_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    try:
        from agent_reach.daily_run.storage.hooks import on_rejected_strategy

        on_rejected_strategy(record, source_path=str(_REJECTED_PATH))
    except Exception:
        pass

    try:
        from agent_reach.daily_run.rejected_strategies_harness import apply_rejected_strategies_harness_refinement
        from agent_reach.daily_run.settings import load_settings

        apply_rejected_strategies_harness_refinement(
            title=str(title).strip(),
            reason=str(reason).strip(),
            source=source,
            settings=settings or load_settings(),
        )
    except Exception:
        pass

    return record


def refresh_rejected_strategies_for_week(
    report: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Saturday weekly refresh: archive expired rows, rewrite active file for next week."""
    cfg = _rejected_cfg(settings)
    if cfg.get("weekly_refresh", True) is False:
        return {"skipped": True, "reason": "weekly_refresh disabled"}

    week_end_raw = str(report.get("week_end") or "")[:10]
    if not week_end_raw:
        return {"skipped": True, "reason": "missing week_end"}

    from agent_reach.daily_run.week_forecast import next_trading_week_range

    target_start, target_end = next_trading_week_range(_parse_iso_date(week_end_raw))
    target_start_s = target_start.isoformat()
    target_end_s = target_end.isoformat()

    all_rows = load_rejected_records(limit=500, settings=settings)
    normalized: list[dict[str, Any]] = []
    for row in all_rows:
        item = dict(row)
        ws, we = _record_week_bounds(item, target_start)
        item["week_start"] = ws
        item["week_end"] = we
        normalized.append(item)

    active_rows = [
        row
        for row in normalized
        if _record_in_week(row, target_start, target_end, as_of=target_start)
    ]
    expired_rows = [
        row
        for row in normalized
        if not _record_in_week(row, target_start, target_end, as_of=target_start)
    ]

    archived = 0
    if cfg.get("archive_expired", True):
        archived = _append_archive_rows(expired_rows)

    added_titles: list[str] = []
    if cfg.get("auto_add_from_weekly", True):
        for title, reason in _candidates_from_weekly_report(report):
            dup = _find_same_week_title(
                title,
                week_start=target_start_s,
                week_end=target_end_s,
                rows=active_rows,
            )
            if dup:
                continue
            record = {
                "id": _next_id(active_rows),
                "title": title,
                "reason": reason,
                "week_start": target_start_s,
                "week_end": target_end_s,
                "source": "weekly_auto",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            active_rows.append(record)
            added_titles.append(title)
            try:
                from agent_reach.daily_run.storage.hooks import on_rejected_strategy

                on_rejected_strategy(record, source_path=str(_REJECTED_PATH))
            except Exception:
                pass

    _write_rejected_records(active_rows)

    if added_titles:
        try:
            from agent_reach.daily_run.rejected_strategies_harness import apply_rejected_strategies_harness_refinement
            from agent_reach.daily_run.settings import load_settings

            apply_rejected_strategies_harness_refinement(
                title=added_titles[0],
                reason="weekly refresh auto-add",
                blocked=added_titles[1:],
                source="weekly_auto",
                settings=settings or load_settings(),
            )
        except Exception:
            pass

    return {
        "skipped": False,
        "target_week_start": target_start_s,
        "target_week_end": target_end_s,
        "active": len(active_rows),
        "archived": archived,
        "added": added_titles,
    }


def filter_rejected_items(
    items: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop improvements/skill items whose title is in rejected library."""
    keys = rejected_title_keys(settings)
    if not keys:
        return list(items), []
    kept: list[dict[str, Any]] = []
    blocked: list[str] = []
    for item in items:
        title = str(item.get("title") or "")
        key = _normalize_title(title)
        if key and key in keys:
            blocked.append(title)
            continue
        kept.append(item)
    return kept, blocked


def render_rejected_markdown(*, limit: int = 8, settings: Optional[dict[str, Any]] = None) -> str:
    rows = load_active_rejected_records(limit=limit, settings=settings)
    if not rows:
        return ""
    lines = ["### ⛔ 已证伪策略（勿重复写回）", ""]
    for row in reversed(rows[-limit:]):
        title = row.get("title") or "?"
        reason = row.get("reason") or ""
        ws = str(row.get("week_start") or "")[:10]
        we = str(row.get("week_end") or "")[:10]
        week_label = f"（{ws}~{we}）" if ws and we else ""
        lines.append(f"- **{title}**{week_label} — {reason}")
    lines.append("")
    return "\n".join(lines)
