# -*- coding: utf-8
"""Team-First 8-expert parallel runner and supervisor review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.plugins.base import PluginResult
from agent_reach.daily_run.plugins.loader import TEAM_EXPERT_NAMES, run_experts

EXPERT_LABELS: dict[str, str] = {
    "fundamental": "基本面大师",
    "technical": "技术分析派",
    "quant": "量化模型师",
    "risk": "风险控制官",
    "macro": "宏观策略师",
    "industry": "行业研究家",
    "sentiment": "消息面猎手",
    "identifier": "专家鉴别Agent",
}


@dataclass
class TeamReview:
    mode: str
    expert_count: int
    consensus_score: float
    consensus_label: str
    conflicts: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
    expert_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "expert_count": self.expert_count,
            "consensus_score": self.consensus_score,
            "consensus_label": self.consensus_label,
            "conflicts": self.conflicts,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "expert_results": self.expert_results,
        }


def run_team_first(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    mode: str = "full_parallel",
    names: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Team-First pipeline: 8 experts in parallel → supervisor review → enrich snapshot.
    """
    team_cfg = settings.get("team", {})
    expert_names = names or team_cfg.get("experts") or TEAM_EXPERT_NAMES
    use_parallel = team_cfg.get("parallel", True)

    enriched = run_experts(
        snapshot,
        settings,
        names=expert_names,
        parallel=use_parallel,
    )

    review = supervisor_review(enriched, settings, mode=mode)
    enriched["team_mode"] = mode
    enriched["team_review"] = review.to_dict()
    enriched["team_consensus_score"] = review.consensus_score
    enriched["team_consensus_label"] = review.consensus_label

    if review.blocked:
        enriched["identifier_blocked"] = True
        enriched.setdefault("downgrade_reasons", []).append(review.block_reason)

    return enriched


def supervisor_review(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    mode: str = "full_parallel",
) -> TeamReview:
    """Aggregate parallel expert outputs; detect conflicts and identifier blocks."""
    results = snapshot.get("expert_results") or []
    scores = snapshot.get("expert_scores") or {}

    if not results:
        return TeamReview(
            mode=mode,
            expert_count=0,
            consensus_score=float(snapshot.get("mss_final") or 50),
            consensus_label="观察",
        )

    values = [float(r.get("score", 50)) for r in results]
    consensus = round(sum(values) / len(values), 1)

    thresholds = settings.get("thresholds", {})
    macro_veto = float(thresholds.get("macro_veto", 40))
    aggressive = float(thresholds.get("aggressive_entry", 50))

    if consensus >= aggressive:
        label = "可做"
    elif consensus >= macro_veto:
        label = "观察"
    else:
        label = "回避"

    conflicts: list[str] = []
    by_name = {r["name"]: float(r["score"]) for r in results}

    tech = by_name.get("technical")
    risk = by_name.get("risk")
    if tech is not None and risk is not None and tech >= aggressive and risk < macro_veto + 5:
        conflicts.append(f"技术面 {tech:.0f} 偏多 vs 风控 {risk:.0f} 偏紧，需 supervisor 仲裁")

    macro = by_name.get("macro")
    sentiment = by_name.get("sentiment")
    if macro is not None and sentiment is not None and abs(macro - sentiment) > 20:
        conflicts.append(f"宏观 {macro:.0f} 与舆情 {sentiment:.0f} 分歧较大")

    identifier = next((r for r in results if r.get("name") == "identifier"), None)
    blocked = False
    block_reason = ""
    if identifier and not identifier.get("success", True):
        blocked = True
        block_reason = f"专家鉴别未通过：{identifier.get('summary', '')}"
        label = "观察"

    return TeamReview(
        mode=mode,
        expert_count=len(results),
        consensus_score=consensus,
        consensus_label=label,
        conflicts=conflicts,
        blocked=blocked,
        block_reason=block_reason,
        expert_results=results,
    )


def render_team_markdown(snapshot: dict[str, Any]) -> str:
    """Render Team-First expert panel for Feishu cards."""
    review = snapshot.get("team_review") or {}
    results = review.get("expert_results") or snapshot.get("expert_results") or []
    mode = review.get("mode") or snapshot.get("team_mode") or "full_parallel"

    lines = [
        f"**👥 Team-First · {len(results)} 专家并行（{mode}）**",
        "",
        f"**Supervisor 共识：** {review.get('consensus_score', snapshot.get('team_consensus_score', '—'))} 分 · "
        f"**{review.get('consensus_label', snapshot.get('team_consensus_label', '观察'))}**",
        "",
        "| 专家 | 评分 | 摘要 |",
        "|------|------|------|",
    ]

    for r in results:
        name = r.get("name", "")
        label = EXPERT_LABELS.get(name, name)
        score = r.get("score", "—")
        summary = str(r.get("summary", ""))[:60]
        flag = " ⚠️" if not r.get("success", True) else ""
        lines.append(f"| {label} | {score} | {summary}{flag} |")

    conflicts = review.get("conflicts") or []
    if conflicts:
        lines.extend(["", "**Supervisor 冲突仲裁：**"])
        for c in conflicts:
            lines.append(f"- {c}")

    if review.get("blocked"):
        lines.extend(["", f"⚠️ **鉴别阻断：** {review.get('block_reason', '')}"])

    return "\n".join(lines)
