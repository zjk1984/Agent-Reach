# -*- coding: utf-8
"""Built-in sentiment expert — flow / social sources."""

from __future__ import annotations

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class SentimentExpert(ExpertPlugin):
    name = "sentiment"
    description = "消息面猎手：资金流、舆情来源"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        breakdown = snap.get("mss_breakdown") or {}
        flow = float(breakdown.get("flow", 50))
        sentiment = float(breakdown.get("sentiment", 50))
        score = round(flow * 0.4 + sentiment * 0.6, 1)

        sources = snap.get("sources") or {}
        parts: list[str] = []
        for key in ("sentiment", "flow"):
            item = sources.get(key)
            if isinstance(item, dict):
                parts.append(str(item.get("summary", key)))
            elif item:
                parts.append(str(item))

        summary = " | ".join(parts) if parts else f"舆情 flow={flow} sentiment={sentiment} → {score}"
        return PluginResult(name=self.name, score=score, summary=summary[:200])
