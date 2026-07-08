# -*- coding: utf-8
"""Discover and run daily-run expert plugins."""

from __future__ import annotations

from typing import Any

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult
from agent_reach.daily_run.plugins.macro_expert import MacroExpert
from agent_reach.daily_run.plugins.sentiment_expert import SentimentExpert
from agent_reach.daily_run.plugins.technical_expert import TechnicalExpert
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.verdict import compute_mss

_BUILTIN: list[ExpertPlugin] = [
    MacroExpert(),
    TechnicalExpert(),
    SentimentExpert(),
]


def list_plugins() -> list[dict[str, str]]:
    return [{"name": p.name, "description": p.description} for p in _BUILTIN]


def get_plugin(name: str) -> ExpertPlugin | None:
    for plugin in _BUILTIN:
        if plugin.name == name:
            return plugin
    return None


def run_experts(
    snapshot: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Run expert plugins and merge scores into snapshot."""
    cfg = settings or load_settings()
    ctx = PluginContext(snapshot=snapshot, settings=cfg)
    selected = _BUILTIN
    if names:
        selected = [p for p in _BUILTIN if p.name in names]
        if not selected:
            raise ValueError(f"未知插件：{names}")

    results: list[PluginResult] = []
    expert_scores: dict[str, float] = {}
    for plugin in selected:
        result = plugin.run(ctx)
        results.append(result)
        expert_scores[plugin.name] = result.score

    merged = dict(snapshot)
    merged["expert_scores"] = expert_scores
    merged["expert_results"] = [r.to_dict() for r in results]

    # Map expert outputs into mss_breakdown when factors missing
    breakdown = dict(merged.get("mss_breakdown") or {})
    if "global" not in breakdown and "macro" in expert_scores:
        breakdown.setdefault("fx", expert_scores["macro"])
        breakdown.setdefault("global", expert_scores["macro"])
    if "flow" not in breakdown and "sentiment" in expert_scores:
        breakdown.setdefault("flow", expert_scores["sentiment"])
        breakdown.setdefault("sentiment", expert_scores["sentiment"])
    if expert_scores.get("technical") is not None:
        breakdown["technical"] = expert_scores["technical"]

    merged["mss_breakdown"] = breakdown
    merged["mss_final"] = compute_mss(breakdown, cfg)
    return merged
