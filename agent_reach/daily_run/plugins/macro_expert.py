# -*- coding: utf-8
"""Built-in macro expert — fx / global + optional Exa/channel enrich."""

from __future__ import annotations

from agent_reach.daily_run.channel_helpers import score_from_text, search_exa_snippet
from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class MacroExpert(ExpertPlugin):
    name = "macro"
    description = "宏观策略师：汇率、全球共振、大宗（支持 Exa 增强）"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        settings = context.settings
        breakdown = snap.get("mss_breakdown") or {}
        fx = float(breakdown.get("fx", 50))
        global_score = float(breakdown.get("global", 50))
        score = round(fx * 0.5 + global_score * 0.5, 1)

        macro = snap.get("macro_summary") or ""
        channel_note = ""

        if settings.get("plugins", {}).get("channel_enrich", True):
            code = snap.get("code") or "A股"
            exa = search_exa_snippet(
                f"China A-share macro northbound flow policy {code} 2026",
                settings,
            )
            if exa:
                channel_note = exa
                score = round((score + score_from_text(exa, score)) / 2, 1)

        summary = macro[:120] if macro else f"宏观分 fx={fx} global={global_score} → {score}"
        if channel_note:
            summary = f"{summary} | {channel_note[:80]}"

        return PluginResult(
            name=self.name,
            score=score,
            summary=summary[:200],
            details={"channel_enriched": bool(channel_note)},
        )
