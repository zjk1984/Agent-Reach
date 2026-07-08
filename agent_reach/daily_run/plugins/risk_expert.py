# -*- coding: utf-8
"""风险控制官 — 仓位、止损、下行风险."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.plugins.base import ExpertPlugin, PluginContext, PluginResult


class RiskExpert(ExpertPlugin):
    name = "risk"
    description = "风险控制官：仓位、止损、宏观否决"

    def run(self, context: PluginContext) -> PluginResult:
        snap = context.snapshot
        thresholds = context.settings.get("thresholds", {})
        trading = context.settings.get("trading", {})
        macro_veto = float(thresholds.get("macro_veto", 40))
        min_cash = float(thresholds.get("min_cash_ratio", 0.4))

        breakdown = snap.get("mss_breakdown") or {}
        mss = snap.get("mss_final")
        if mss is None:
            weights = context.settings.get("mss_weights", {})
            total = sum(float(breakdown.get(k, 50)) * float(weights.get(k, 0.25)) for k in weights)
            mss = total

        portfolio = snap.get("portfolio") or {}
        cash_ratio = _f(portfolio.get("cash_ratio"))
        price = _f(snap.get("price"))
        ma20 = _f(snap.get("ma20"))

        score = 60.0
        notes: list[str] = []
        flags: list[str] = []

        if float(mss) < macro_veto:
            score -= 25
            flags.append("macro_veto")
            notes.append(f"MSS {float(mss):.0f} 触发宏观一票否决")

        if cash_ratio is not None:
            if cash_ratio >= min_cash:
                score += 10
                notes.append(f"现金 {cash_ratio:.0%} ≥ {min_cash:.0%}")
            else:
                score -= 15
                flags.append("low_cash")
                notes.append(f"现金 {cash_ratio:.0%} 低于风控线")

        if price is not None and ma20 is not None:
            stop_pct = float(trading.get("stop_loss_ma20_pct", 0.04))
            stop = min(ma20, price * (1 - stop_pct))
            if price < ma20:
                score -= 10
                notes.append(f"跌破 MA20，止损参考 {stop:.2f}")
            else:
                notes.append(f"MA20 上方，止损 {stop:.2f}")

        score = max(0.0, min(100.0, score))
        return PluginResult(
            name=self.name,
            score=round(score, 1),
            summary="；".join(notes) or f"风控评分 {score:.0f}",
            details={"flags": flags, "cash_ratio": cash_ratio},
        )


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
