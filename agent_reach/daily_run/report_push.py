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
    "weekly_portfolio": "盈亏·持仓",
    "weekly_market": "板块·热点",
    "weekly_track": "MSS·经验",
    "weekly_insights": "学习·改进",
    "forecast_mss": "MSS预测",
    "forecast_symbols": "个股路径",
    "forecast_news": "新闻热点",
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
    kind_icon = {"morning": "🌅", "close": "🧠", "forecast": "🔮"}.get(report_kind, "📋")
    kind_label = {"morning": "早盘", "close": "收盘", "forecast": "下周预测"}.get(
        report_kind, report_kind
    )
    label = _CATEGORY_LABELS.get(category, category)
    title = f"{kind_icon} {kind_label} {index}/{total} · {label} · {name}"
    if extra:
        title += f" · {extra}"
    return title


def _report_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("report") or {}


def split_push_enabled(settings: dict[str, Any], *, report_kind: str) -> bool:
    """report_kind: morning | close | weekly | forecast"""
    cfg = _report_cfg(settings)
    if cfg.get("split_push", True) is False:
        return False
    key = f"{report_kind}_split_push"
    if key in cfg:
        return bool(cfg[key])
    if report_kind == "weekly":
        weekly = settings.get("weekly_report") or {}
        if "split_push" in weekly:
            return bool(weekly["split_push"])
    if report_kind == "forecast":
        wf = settings.get("week_forecast") or {}
        if "split_push" in wf:
            return bool(wf["split_push"])
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


_WEEKLY_CATEGORY_MAP = {
    "盈亏·持仓": "weekly_portfolio",
    "板块·热点": "weekly_market",
    "MSS·经验": "weekly_track",
    "学习·改进": "weekly_insights",
}


def render_weekly_push_sections(report) -> list[ReportSection]:
    """Convert WeeklyReport sections to ReportSection for unified push."""
    from agent_reach.daily_run.weekly_report import render_weekly_sections, weekly_section_title

    raw = render_weekly_sections(report)
    total = len(raw)
    sections: list[ReportSection] = []
    for i, sec in enumerate(raw, start=1):
        if not (sec.markdown or "").strip():
            continue
        category = _WEEKLY_CATEGORY_MAP.get(sec.label, f"weekly_{i}")
        sections.append(
            ReportSection(
                category=category,
                title=weekly_section_title(report, i, total, sec.label),
                body=sec.markdown.strip(),
            )
        )
    return sections


_FORECAST_CATEGORY_MAP = {
    "MSS预测": "forecast_mss",
    "个股路径": "forecast_symbols",
    "新闻热点": "forecast_news",
}


def render_forecast_push_sections(forecast) -> list[ReportSection]:
    """Convert WeekForecast sections to ReportSection for unified push."""
    from agent_reach.daily_run.week_forecast import forecast_section_title, render_forecast_sections

    raw = render_forecast_sections(forecast)
    total = len(raw)
    sections: list[ReportSection] = []
    for i, sec in enumerate(raw, start=1):
        if not (sec.markdown or "").strip():
            continue
        category = _FORECAST_CATEGORY_MAP.get(sec.label, f"forecast_{i}")
        sections.append(
            ReportSection(
                category=category,
                title=forecast_section_title(forecast, i, total, sec.label),
                body=sec.markdown.strip(),
            )
        )
    return sections


def merged_category_title(
    *,
    report_kind: str,
    category: str,
    index: int,
    total: int,
    symbol_count: int,
) -> str:
    """Title for a category card merged across multiple symbols."""
    kind_icon = {"morning": "🌅", "close": "🧠", "intraday": "📊"}.get(report_kind, "📋")
    kind_label = {"morning": "早盘", "close": "收盘", "intraday": "盘中"}.get(report_kind, report_kind)
    label = _CATEGORY_LABELS.get(category, category)
    return f"{kind_icon} {kind_label} {index}/{total} · {label} · {symbol_count}只"


def merge_sections_by_category(
    groups: list[tuple[str, list[ReportSection]]],
    *,
    report_kind: str,
) -> list[ReportSection]:
    """Merge per-symbol sections into one card per category (experts, decision, …)."""
    order: list[str] = []
    buckets: dict[str, list[tuple[str, str]]] = {}

    for symbol_name, sections in groups:
        for sec in sections:
            if not (sec.body or "").strip():
                continue
            if sec.category not in buckets:
                order.append(sec.category)
                buckets[sec.category] = []
            buckets[sec.category].append((symbol_name, sec.body.strip()))

    merged: list[ReportSection] = []
    total = len(order)
    for i, cat in enumerate(order, start=1):
        rows = buckets[cat]
        body_parts = [f"## {name}\n\n{content}" for name, content in rows]
        merged.append(
            ReportSection(
                category=cat,
                title=merged_category_title(
                    report_kind=report_kind,
                    category=cat,
                    index=i,
                    total=total,
                    symbol_count=len(rows),
                ),
                body="\n\n---\n\n".join(body_parts),
            )
        )
    return merged


def morning_sections_from_run(run_result: dict[str, Any]) -> list[ReportSection]:
    evaluation = run_result.get("evaluation") or {}
    report = evaluation.get("report") or {}
    return render_morning_sections(
        team_markdown=run_result.get("team_markdown") or "",
        report_markdown=run_result.get("report_markdown") or "",
        report=report,
    )


def close_sections_from_run(run_result: dict[str, Any], *, verify_name: str) -> list[ReportSection]:
    return render_close_sections(
        verify_name=verify_name,
        team_markdown=run_result.get("team_markdown") or "",
        curve_markdown=run_result.get("curve_markdown") or "",
        research_markdown=run_result.get("research_markdown") or "",
        experience_markdown=run_result.get("experience_markdown") or "",
        verify_markdown=run_result.get("verify_markdown") or "",
    )


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
    feishu_cfg = cfg.get("feishu") or {}
    max_retries = int(feishu_cfg.get("send_max_retries", 3))
    backoff_raw = feishu_cfg.get("send_backoff_seconds") or [1, 2, 4]
    backoff = tuple(float(x) for x in backoff_raw)
    fallback_plaintext = feishu_cfg.get("fallback_plaintext_on_card_error", True) is not False

    def _send(title: str, markdown: str, tpl: str) -> dict[str, Any]:
        return send_card(
            cfg_obj,
            title,
            markdown,
            template=tpl,
            split_tables=split_tables,
            interval_seconds=interval if split_tables else 0.0,
            max_retries=max_retries,
            backoff=backoff,
            fallback_plaintext=fallback_plaintext,
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
