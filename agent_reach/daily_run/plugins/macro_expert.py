# -*- coding: utf-8
"""Built-in macro expert — fx / global resonance scoring."""

from __future__ import annotations

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class MacroExpert(ExpertPlugin):
    name = "macro"
    description = "宏观策略师：汇率、全球共振、大宗"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        breakdown = snap.get("mss_breakdown") or {}
        fx = float(breakdown.get("fx", 50))
        global_score = float(breakdown.get("global", 50))
        score = round(fx * 0.5 + global_score * 0.5, 1)
        macro = snap.get("macro_summary") or ""
        summary = macro[:120] if macro else f"宏观分 fx={fx} global={global_score} → {score}"
        return PluginResult(name=self.name, score=score, summary=summary)
