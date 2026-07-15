# -*- coding: utf-8
"""Weekly skill learning and process improvement (optional enrichments)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class SkillLearningItem:
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "summary": self.summary, "source": self.source, "url": self.url}


@dataclass
class InsightItem:
    title: str
    detail: str = ""
    priority: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "detail": self.detail, "priority": self.priority}


def generate_skill_learning(
    *,
    settings: dict[str, Any],
    hot_sectors: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    experience_snippets: list[str],
    manifests: list[dict[str, Any]],
) -> tuple[list[SkillLearningItem], list[dict[str, Any]]]:
    """Optional FindSkills integration; returns empty when disabled."""
    cfg = settings.get("weekly_report") or {}
    if cfg.get("skill_learning", False) is not True:
        return [], []
    try:
        from agent_reach.daily_run.findskills_client import discover_skills_for_weekly

        return discover_skills_for_weekly(
            hot_sectors=hot_sectors,
            holdings=holdings,
            experience_snippets=experience_snippets,
            settings=settings,
        )
    except Exception:
        return [], []


def generate_weekly_improvements(
    *,
    settings: dict[str, Any],
    week_start: date,
    week_end: date,
    manifests: list[dict[str, Any]],
    weekly_pnl: Optional[float],
    weekly_pnl_pct: Optional[float],
    holdings: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    mss_summary: list[dict[str, Any]],
    experience_snippets: list[str],
    hot_sectors: list[dict[str, Any]],
) -> list[InsightItem]:
    items: list[InsightItem] = []
    if weekly_pnl is not None and weekly_pnl_pct is not None and weekly_pnl_pct < -2:
        items.append(
            InsightItem(
                title="本周回撤偏大",
                detail=f"组合净值变动 {weekly_pnl:+,.0f}（{weekly_pnl_pct:+.2f}%），建议复盘 MSS 与仓位。",
                priority="high",
            )
        )
    if not manifests:
        items.append(
            InsightItem(
                title="缺少 daily-run manifest",
                detail="本周无 manifest 记录，周报 PnL/MSS 可能不完整。请确认 cron/GHA 已运行。",
                priority="high",
            )
        )
    return items


def render_skill_learning_markdown(
    items: list[SkillLearningItem],
    research: list[dict[str, Any]],
) -> str:
    if not items and not research:
        return ""
    lines = ["## 🧩 技能学习"]
    for item in items:
        lines.append(f"- **{item.title}** — {item.summary}")
    for r in research:
        if r.get("summary"):
            lines.append(f"- {r.get('label', 'research')}: {r['summary'][:200]}")
    return "\n".join(lines)


def render_improvements_markdown(items: list[InsightItem]) -> str:
    if not items:
        return ""
    lines = ["## 🔧 流程改进建议"]
    for item in items:
        lines.append(f"- **{item.title}** — {item.detail}")
    return "\n".join(lines)
