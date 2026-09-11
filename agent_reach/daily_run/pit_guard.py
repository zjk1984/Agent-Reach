# -*- coding: utf-8
"""Point-in-Time guard — extend lookahead audit with signal lag and save-time gate."""

from __future__ import annotations

from typing import Any, Optional


def pit_guard_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("pit_guard") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "block_on_fail": block.get("block_on_fail", True) is not False,
        "audit_in_snapshot": block.get("audit_in_snapshot", True) is not False,
        "signal_lag_days": max(0, int(block.get("signal_lag_days", 1))),
        "merge_lookahead": block.get("merge_lookahead", True) is not False,
        "block_save_on_fail": block.get("block_save_on_fail", False) is True,
        "enforce_without_audit": block.get("enforce_without_audit", False) is True,
    }


def audit_snapshot_pit(
    snapshot: dict[str, Any],
    *,
    job: str = "intraday",
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = pit_guard_cfg(settings)
    if not cfg["enabled"]:
        return {
            "ok": True,
            "skipped": True,
            "job": job,
            "finding_count": 0,
            "findings": [],
        }

    findings: list[str] = []
    if cfg["merge_lookahead"]:
        from agent_reach.daily_run.lookahead_audit import audit_snapshot_lookahead

        la = audit_snapshot_lookahead(snapshot, job=job, settings=settings)
        findings.extend(list(la.get("findings") or []))

    report_type = str(snapshot.get("report_type") or job or "").lower()
    signal_lag = int(cfg["signal_lag_days"])
    if signal_lag >= 1 and report_type == "intraday":
        if snapshot.get("morning_baseline_same_day") and not snapshot.get("signal_lag_applied"):
            findings.append(
                f"intraday 使用当日 morning baseline 但未标记 signal_lag={signal_lag}，"
                "存在 T 日信号 T 日成交前视风险"
            )

    for sym in snapshot.get("symbols") or []:
        if not isinstance(sym, dict):
            continue
        period = sym.get("report_period") or sym.get("financial_period")
        visible = sym.get("report_visible_date") or sym.get("announce_date")
        as_of = snapshot.get("as_of")
        if period and visible and as_of and str(visible) > str(as_of)[:10]:
            code = sym.get("code") or "?"
            findings.append(f"{code} 财报 period={period} 可见日晚于 snapshot.as_of（PIT 违规）")

    if report_type in {"morning", "premarket"} and snapshot.get("uses_eod_macro") is True:
        findings.append("morning/premarket snapshot 标记 uses_eod_macro，疑似使用收盘宏观数据")

    return {
        "ok": not findings,
        "skipped": False,
        "job": job,
        "finding_count": len(findings),
        "findings": findings,
        "signal_lag_days": signal_lag,
        "as_of": snapshot.get("as_of"),
        "report_type": report_type,
    }


def apply_pit_guard_to_snapshot(
    snapshot: dict[str, Any],
    *,
    job: str = "intraday",
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    result = audit_snapshot_pit(snapshot, job=job, settings=settings)
    if pit_guard_cfg(settings).get("audit_in_snapshot"):
        snapshot["pit_guard"] = result
    return result


def pit_guard_block_reason(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    job: str = "intraday",
) -> Optional[str]:
    cfg = pit_guard_cfg(settings)
    if not cfg["enabled"] or not cfg["block_on_fail"]:
        return None
    audit = snapshot.get("pit_guard")
    if not isinstance(audit, dict):
        if not cfg["enforce_without_audit"]:
            return None
        audit = audit_snapshot_pit(snapshot, job=job, settings=settings)
    if audit.get("ok") is not False:
        return None
    first = (audit.get("findings") or ["PIT 审计未通过"])[0]
    return f"pit_guard：{first}"


def render_pit_guard_markdown(result: dict[str, Any]) -> str:
    if result.get("skipped"):
        return "## PIT Guard\n\n已跳过。"
    if result.get("ok"):
        return "## ✅ PIT Guard\n\n未发现 Point-in-Time / 前视风险。"
    lines = ["## ⚠️ PIT Guard", ""]
    for item in result.get("findings") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)
