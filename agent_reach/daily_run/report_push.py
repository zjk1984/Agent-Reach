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
        sections.append(
            ReportSection(
                category="experts",
                title=f"🌅 早盘 · 专家共识 · {name}",
                body=team_markdown.strip(),
            )
        )
    if report_markdown.strip():
        sections.append(
            ReportSection(
                category="decision",
                title=f"🌅 早盘 · MSS 决策 · {name} · {verdict}",
                body=report_markdown.strip(),
            )
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
        sections.append(
            ReportSection(
                category="experts",
                title=f"🧠 收盘 · 专家观点 · {label}",
                body=team_markdown.strip(),
            )
        )
    if curve_markdown.strip():
        sections.append(
            ReportSection(
                category="intraday",
                title=f"🧠 收盘 · 盘中曲线 · {label}",
                body=curve_markdown.strip(),
            )
        )
    if research_markdown.strip():
        sections.append(
            ReportSection(
                category="research",
                title=f"🧠 收盘 · Exa 调研 · {label}",
                body=research_markdown.strip(),
            )
        )
    if experience_markdown.strip():
        sections.append(
            ReportSection(
                category="experience",
                title=f"🧠 收盘 · 经验沉淀 · {label}",
                body=experience_markdown.strip(),
            )
        )
    if verify_markdown.strip():
        sections.append(
            ReportSection(
                category="verify",
                title=f"🧠 收盘 · 验证结论 · {label}",
                body=verify_markdown.strip(),
            )
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

    def _send(title: str, markdown: str, tpl: str) -> dict[str, Any]:
        return send_card(cfg_obj, title, markdown, template=tpl)

    if not split or len(bodies) == 1:
        combined = "\n\n---\n\n".join(s.body for s in bodies)
        title = bodies[0].title if len(bodies) == 1 else fallback_title
        result = _send(title, combined, tpl_default)
        return {"mode": "single", "count": 1, "results": [result], "feishu": result}

    interval = float(cfg.get("split_push_interval_seconds", 0.3))
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, sec in enumerate(bodies):
        try:
            r = _send(sec.title, sec.body, sec.template or tpl_default)
            results.append({"category": sec.category, "title": sec.title, "feishu": r})
        except FeishuError as exc:
            errors.append(f"{sec.category}: {exc}")
        if i + 1 < len(bodies):
            time.sleep(interval)

    if not results and errors:
        raise FeishuError(errors[0])

    out: dict[str, Any] = {
        "mode": "split",
        "count": len(results),
        "results": results,
        "feishu": results[-1]["feishu"] if results else None,
    }
    if errors:
        out["push_errors"] = errors
    return out
