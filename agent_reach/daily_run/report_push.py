# -*- coding: utf-8
"""Split Feishu push for morning / close reports by category."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ReportSection:
    category: str
    title: str
    body: str
    template: Optional[str] = None


_CATEGORY_LABELS: dict[str, str] = {
    "experts": "专家共识",
    "decision": "MSS 决策",
    "intraday": "盘中曲线",
    "research": "Exa 调研",
    "experience": "经验沉淀",
    "verify": "验证结论",
}


def section_title(
    *,
    report_kind: str,
    category: str,
    name: str,
    index: int,
    total: int,
    extra: str = "",
) -> str:
    """Numbered section title (aligned with weekly report split push)."""
    kind_icon = {"morning": "🌅", "close": "🧠"}.get(report_kind, "📋")
    kind_label = {"morning": "早盘", "close": "收盘"}.get(report_kind, report_kind)
    label = _CATEGORY_LABELS.get(category, category)
    title = f"{kind_icon} {kind_label} {index}/{total} · {label} · {name}"
    if extra:
        title += f" · {extra}"
    return title


def _report_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("report") or {}


def split_push_enabled(settings: dict[str, Any], *, report_kind: str) -> bool:
    """report_kind: morning | close | weekly"""
    cfg = _report_cfg(settings)
    if cfg.get("split_push", True) is False:
        return False
    key = f"{report_kind}_split_push"
    if key in cfg:
        return bool(cfg[key])
    return True


def render_morning_sections(
    *,
    team_markdown: str,
    report_markdown: str,
    report: dict[str, Any],
) -> list[ReportSection]:
    name = report.get("name") or report.get("code") or "大盘"
    verdict = report.get("verdict") or "观察"
    sections: list[ReportSection] = []
    if team_markdown.strip():
        sections.append(ReportSection(category="experts", title="", body=team_markdown.strip()))
    if report_markdown.strip():
        sections.append(
            ReportSection(category="decision", title="", body=report_markdown.strip(), template=None)
        )
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        extra = verdict if sec.category == "decision" else ""
        sec.title = section_title(
            report_kind="morning",
            category=sec.category,
            name=name,
            index=i,
            total=total,
            extra=extra,
        )
    return sections


def render_close_sections(
    *,
    verify_name: str,
    team_markdown: str = "",
    curve_markdown: str = "",
    research_markdown: str = "",
    experience_markdown: str = "",
    verify_markdown: str = "",
) -> list[ReportSection]:
    label = verify_name or "大盘"
    sections: list[ReportSection] = []
    if team_markdown.strip():
        sections.append(ReportSection(category="experts", title="", body=team_markdown.strip()))
    if curve_markdown.strip():
        sections.append(ReportSection(category="intraday", title="", body=curve_markdown.strip()))
    if research_markdown.strip():
        sections.append(ReportSection(category="research", title="", body=research_markdown.strip()))
    if experience_markdown.strip():
        sections.append(ReportSection(category="experience", title="", body=experience_markdown.strip()))
    if verify_markdown.strip():
        sections.append(ReportSection(category="verify", title="", body=verify_markdown.strip()))
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        sec.title = section_title(
            report_kind="close",
            category=sec.category,
            name=label,
            index=i,
            total=total,
        )
    return sections


def push_report_sections(
    sections: list[ReportSection],
    *,
    settings: dict[str, Any],
    config,
    report_type: str,
    fallback_title: str,
    template: Optional[str] = None,
    split: bool = True,
) -> dict[str, Any]:
    """Push one combined card or multiple category cards to Feishu."""
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    bodies = [s for s in sections if s.body.strip()]
    if not bodies:
        raise FeishuError("无可推送的报告内容")

    cfg = _report_cfg(settings)
    tpl_default = template or cfg.get(f"feishu_template_{report_type}", "blue")
    cfg_obj = config or Config()

    interval = float(cfg.get("split_push_interval_seconds", 0.3))
    split_tables = cfg.get("feishu_split_tables", True) is not False

    def _send(title: str, markdown: str, tpl: str) -> dict[str, Any]:
        return send_card(
            cfg_obj,
            title,
            markdown,
            template=tpl,
            split_tables=split_tables,
            interval_seconds=interval if split_tables else 0.0,
        )

    if not split or len(bodies) == 1:
        combined = "\n\n---\n\n".join(s.body for s in bodies)
        title = bodies[0].title if len(bodies) == 1 else fallback_title
        result = _send(title, combined, tpl_default)
        card_count = result.get("cards", 1)
        return {
            "mode": "single",
            "count": card_count,
            "results": [{"feishu": result}],
            "feishu": result.get("feishu", result),
        }

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    card_count = 0
    for i, sec in enumerate(bodies):
        try:
            r = _send(sec.title, sec.body, sec.template or tpl_default)
            n = r.get("cards", 1)
            card_count += n
            results.append({"category": sec.category, "title": sec.title, "cards": n, "feishu": r})
        except FeishuError as exc:
            errors.append(f"{sec.category}: {exc}")
        if i + 1 < len(bodies):
            time.sleep(interval)

    if not results and errors:
        raise FeishuError(errors[0])

    out: dict[str, Any] = {
        "mode": "split",
        "count": card_count or len(results),
        "sections": len(results),
        "results": results,
        "feishu": results[-1]["feishu"] if results else None,
    }
    if errors:
        out["push_errors"] = errors
    return out
