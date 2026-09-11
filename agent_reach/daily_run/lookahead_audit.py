# -*- coding: utf-8
"""Lookahead / future-data audit (Freqtrade lookahead-analysis inspired)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def audit_snapshot_lookahead(
    snapshot: dict[str, Any],
    *,
    job: str = "intraday",
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    findings: list[str] = []
    as_of = _parse_iso(snapshot.get("as_of"))
    report_type = str(snapshot.get("report_type") or job or "").lower()

    macro = snapshot.get("macro_ctx") or snapshot.get("macro") or {}
    macro_as_of = _parse_iso(macro.get("as_of") or macro.get("fetched_at"))
    if as_of and macro_as_of and macro_as_of > as_of:
        findings.append("macro_ctx 时间戳晚于 snapshot.as_of，可能存在前视")

    for sym in snapshot.get("symbols") or []:
        if not isinstance(sym, dict):
            continue
        sym_as_of = _parse_iso(sym.get("as_of") or sym.get("quote_at"))
        if as_of and sym_as_of and sym_as_of > as_of:
            code = sym.get("code") or "?"
            findings.append(f"{code} 报价 as_of 晚于 snapshot.as_of")

    history = snapshot.get("mss_history") or []
    if as_of and isinstance(history, list):
        for row in history:
            if not isinstance(row, dict):
                continue
            ts = _parse_iso(row.get("as_of") or row.get("at"))
            if ts and ts > as_of:
                findings.append("mss_history 含未来时间点")

    if report_type in {"morning", "intraday"} and snapshot.get("close_price") is not None:
        findings.append("morning/intraday snapshot 含 close_price 字段，疑似使用收盘价决策")

    fill_timing = str(
        ((settings or {}).get("execution_sim") or {}).get("fill_timing")
        or ((settings or {}).get("trading") or {}).get("fill_timing")
        or "close"
    )
    # fill_timing=close in live intraday uses snapshot.price (live quote), not EOD close.
    # Only flag outside continuous matching when session is not explicitly closed —
    # matches trade_calendar session gate and avoids false blocks 09:30–14:57.
    if report_type == "intraday" and fill_timing == "close" and not snapshot.get("session_closed"):
        from agent_reach.daily_run.trade_calendar import is_continuous_session

        if not is_continuous_session(as_of):
            findings.append(
                "intraday 使用 fill_timing=close 但未标记 session_closed，存在前视成交风险"
            )

    verdict = str(snapshot.get("verdict") or "")
    if report_type == "morning" and snapshot.get("live_macro_fetch") is False and verdict == "可做":
        findings.append("早盘 macro 非实时拉取但 verdict=可做，需复核信号时效")

    return {
        "ok": not findings,
        "job": job,
        "finding_count": len(findings),
        "findings": findings,
        "as_of": snapshot.get("as_of"),
        "report_type": report_type,
    }


def render_lookahead_audit_markdown(result: dict[str, Any]) -> str:
    if result.get("ok"):
        return "## ✅ Lookahead 审计\n\n未发现明显前视/未来数据风险。"
    lines = ["## ⚠️ Lookahead 审计", ""]
    for item in result.get("findings") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)
