# -*- coding: utf-8
"""Enforce midday→PM trim flags or record explicit skip reasons before close."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import is_afternoon_session, today_shanghai


def _pm_trim_cfg(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    raw = dict(((settings or {}).get("intraday") or {}).get("midday_pm_trim") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "min_scan_num": int(raw.get("min_scan_num", 8)),
        "final_scan_num": int(raw.get("final_scan_num", 11)),
    }


def midday_trim_codes(settings: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    """Codes flagged 减仓 in today's midday handoff afternoon_adjustments."""
    from agent_reach.daily_run.midday_handoff import load_midday_handoff

    payload = load_midday_handoff(midday_day=today_shanghai()) or {}
    out: dict[str, dict[str, Any]] = {}
    for adj in payload.get("afternoon_adjustments") or []:
        if not isinstance(adj, dict):
            continue
        if str(adj.get("adjusted_plan") or "") != "减仓":
            continue
        code = _normalize_code(str(adj.get("code") or ""))
        if code:
            out[code] = dict(adj)
    return out


def afternoon_scan_num(scans: list[dict[str, Any]]) -> int:
    for scan in reversed(scans or []):
        sid = str(scan.get("scan_id") or "")
        if sid.startswith("S") and sid[1:].isdigit():
            return int(sid[1:])
    return len(scans or [])


def pm_trim_active_for_code(
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    scans: Optional[list[dict[str, Any]]] = None,
) -> bool:
    cfg = _pm_trim_cfg(settings)
    if not cfg["enabled"]:
        return False
    if not is_afternoon_session():
        return False
    norm = _normalize_code(code)
    if not norm or norm not in midday_trim_codes(settings):
        return False
    scan_num = afternoon_scan_num(list(scans or []))
    return scan_num >= cfg["min_scan_num"]


def pm_trim_skip_manifest_path(day: Optional[date] = None) -> Path:
    d = day or today_shanghai()
    handoff_dir = Path.home() / ".agent-reach" / "daily_run" / "handoff"
    return handoff_dir / f"pm_trim_skips_{d.isoformat()}.json"


def record_pm_trim_skip(
    code: str,
    *,
    reason: str,
    scan_id: str,
    settings: Optional[dict[str, Any]] = None,
    decision: Optional[dict[str, Any]] = None,
) -> Path:
    """Persist explicit skipped_reason when midday 减仓 did not execute."""
    day = today_shanghai()
    path = pm_trim_skip_manifest_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    norm = _normalize_code(code)
    entries = [e for e in (payload.get("skips") or []) if _normalize_code(str(e.get("code") or "")) != norm]
    entries.append(
        {
            "code": norm,
            "scan_id": scan_id,
            "skipped_reason": str(reason)[:240],
            "decision": decision or {},
            "midday_adjust": midday_trim_codes(settings).get(norm),
        }
    )
    payload.update(
        {
            "date": day.isoformat(),
            "skips": entries,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def finalize_pm_trim_obligations(
    state: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    At final afternoon scan (S11), record skip for any midday 减仓 code without a PM sell.
    """
    cfg = _pm_trim_cfg(settings)
    if not cfg["enabled"]:
        return []
    scans = list(state.get("scans") or [])
    if afternoon_scan_num(scans) < cfg["final_scan_num"]:
        return []
    flagged = midday_trim_codes(settings)
    if not flagged:
        return []

    sold_codes: set[str] = set()
    for trade in state.get("trades") or []:
        if not isinstance(trade, dict):
            continue
        if trade.get("action") != "sell" or trade.get("portfolio_applied") is not True:
            continue
        code = _normalize_code(str(trade.get("code") or ""))
        if code:
            sold_codes.add(code)

    recorded: list[dict[str, Any]] = []
    scan_id = str(scans[-1].get("scan_id") or "S?") if scans else "S?"
    for code in flagged:
        if code in sold_codes:
            continue
        reason = "午盘计划减仓，下午未执行（无成交且无显式 skip）"
        record_pm_trim_skip(
            code,
            reason=reason,
            scan_id=scan_id,
            settings=settings,
            decision={"action": "hold", "blocked": True, "block_kind": "midday_trim_pending"},
        )
        recorded.append({"code": code, "skipped_reason": reason})
    return recorded
