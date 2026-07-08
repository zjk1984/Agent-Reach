# -*- coding: utf-8
"""Built-in technical expert — MA / position / volume."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class TechnicalExpert(ExpertPlugin):
    name = "technical"
    description = "技术分析派：均线、20日位置、量比"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        thresholds = context.settings.get("thresholds", {})
        price = _f(snap.get("price"))
        ma20 = _f(snap.get("ma20"))
        pos = _f(snap.get("position_20d"))
        vol = _f(snap.get("volume_ratio"))

        if price is None or ma20 is None:
            return PluginResult(
                name=self.name,
                score=45.0,
                summary="缺少 price/ma20，技术面降级为中性",
                success=False,
            )

        score = 50.0
        notes: list[str] = []

        if price > ma20:
            score += 15
            notes.append("收盘>MA20")
        else:
            score -= 15
            notes.append("收盘<MA20")

        high_pos = float(thresholds.get("high_position_20d", 0.7))
        if pos is not None:
            if 0.4 <= pos <= 0.6:
                score += 10
                notes.append(f"20日位置 {pos:.0%} 合理")
            elif pos > high_pos:
                score -= 10
                notes.append(f"20日位置 {pos:.0%} 偏高")

        min_vol = float(thresholds.get("min_volume_ratio", 1.0))
        if vol is not None:
            if vol >= min_vol:
                score += 5
                notes.append(f"量比 {vol:.2f}")
            else:
                score -= 5
                notes.append(f"量比 {vol:.2f} 偏弱")

        score = max(0.0, min(100.0, score))
        return PluginResult(
            name=self.name,
            score=round(score, 1),
            summary="；".join(notes) or f"技术评分 {score:.0f}",
            details={"price": price, "ma20": ma20, "position_20d": pos, "volume_ratio": vol},
        )


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
