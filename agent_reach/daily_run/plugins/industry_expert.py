# -*- coding: utf-8
"""行业研究家 — 景气度、竞争格局、板块驱动."""

from __future__ import annotations

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class IndustryExpert(ExpertPlugin):
    name = "industry"
    description = "行业研究家：景气度、竞争格局、板块驱动"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        watchlist = snap.get("watchlist") or []
        macro = snap.get("macro_summary") or ""
        breakdown = snap.get("mss_breakdown") or {}
        global_score = float(breakdown.get("global", 50))

        score = global_score * 0.6 + 50 * 0.4
        notes: list[str] = []

        if macro:
            notes.append(macro[:80])

        hot_sectors: list[str] = []
        for item in watchlist:
            chg = item.get("change_pct")
            name = item.get("name") or item.get("code")
            if chg is not None and float(chg) > 2:
                hot_sectors.append(f"{name} {float(chg):+.1f}%")
                score += 3
        if hot_sectors:
            notes.append("观察池强势：" + "、".join(hot_sectors[:3]))

        industry_tag = snap.get("industry") or snap.get("sector")
        if industry_tag:
            notes.insert(0, f"行业：{industry_tag}")

        score = max(0.0, min(100.0, score))
        return PluginResult(
            name=self.name,
            score=round(score, 1),
            summary="；".join(notes) if notes else f"行业评分 {score:.0f}",
            details={"watchlist_count": len(watchlist)},
        )
