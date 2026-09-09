# -*- coding: utf-8
"""Lite report audit gate for daily-run cards (ai-berkshire report_audit inspired)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def berkshire_report_audit_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("report_audit") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "require_as_of": block.get("require_as_of", True) is not False,
        "require_quote_source": block.get("require_quote_source", True) is not False,
        "block_on_rigor_fail": block.get("block_on_rigor_fail", False) is True,
    }


def audit_card_context(
    *,
    snapshot: Optional[dict[str, Any]] = None,
    report_md: str = "",
    settings: Optional[dict[str, Any]] = None,
    financial_checks: Optional[dict[str, Any]] = None,
    research_results: Optional[list[dict[str, Any]]] = None,
    workflow: str = "close",
) -> dict[str, Any]:
    """Return warnings + card prefix for missing cutoff / rigor / research gaps."""
    from agent_reach.daily_run.berkshire.config import berkshire_enabled

    cfg = berkshire_report_audit_cfg(settings)
    if not berkshire_enabled(settings) or not cfg.get("enabled", True):
        return {"passed": True, "warnings": [], "prefix": "", "skipped": True}

    warnings: list[str] = []
    snap = snapshot or {}

    if cfg.get("require_as_of") and not str(snap.get("as_of") or "").strip():
        warnings.append("缺少 data cutoff (as_of)，请在报告头标注数据截止日")

    if cfg.get("require_quote_source"):
        sources = snap.get("sources") or {}
        quote_src = sources.get("quote") or {}
        if not quote_src and snap.get("price") is None:
            warnings.append("缺少行情来源标注（sources.quote）")

    if financial_checks:
        mc = financial_checks.get("market_cap") or {}
        if mc.get("ok") is False:
            warnings.append(str(mc.get("message") or "财务验算：市值偏差超标"))
        elif mc.get("skipped") and workflow in ("close", "weekly"):
            warnings.append("财务验算跳过：缺股本/市值字段（可启用 ashare 补全）")

    if research_results is not None:
        failed = [r for r in research_results if not r.get("success")]
        if failed and len(failed) == len(research_results):
            warnings.append(f"深度调研全部失败（{len(failed)} 条 Exa 限流或未就绪）")

    passed = len(warnings) == 0
    if cfg.get("block_on_rigor_fail") and not passed:
        prefix = "⛔ "
    elif warnings:
        prefix = "⚠️ "
    else:
        prefix = ""

    return {
        "passed": passed,
        "warnings": warnings,
        "prefix": prefix,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "workflow": workflow,
    }


def render_report_audit_markdown(audit: dict[str, Any]) -> str:
    if audit.get("skipped") or not audit.get("warnings"):
        return ""
    lines = ["**📋 研究质检（report_audit lite）**", ""]
    for warning in audit.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    return "\n".join(lines)
