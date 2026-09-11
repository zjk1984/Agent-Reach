# -*- coding: utf-8
"""Risk panel — extend weekly risk metrics with IR/alerts (Qlib risk_analysis inspired)."""

from __future__ import annotations

import math
import statistics
from typing import Any, Optional


def risk_panel_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("risk_panel") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "max_drawdown_alert_pct": float(block.get("max_drawdown_alert_pct", 5.0)),
        "min_information_ratio": float(block.get("min_information_ratio", 0.0)),
        "append_to_weekly_card": block.get("append_to_weekly_card", True) is not False,
        "append_to_close_summary": block.get("append_to_close_summary", True) is not False,
    }


def _daily_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return out


def _information_ratio(daily_rets: list[float], bench_rets: list[float]) -> Optional[float]:
    n = min(len(daily_rets), len(bench_rets))
    if n < 2:
        return None
    excess = [daily_rets[i] - bench_rets[i] for i in range(n)]
    std = statistics.pstdev(excess)
    if std <= 1e-12:
        return None
    return round(statistics.mean(excess) / std * math.sqrt(252), 3)


def build_risk_panel(
    *,
    risk_metrics: dict[str, Any],
    daily_totals: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = risk_panel_cfg(settings)
    if not cfg["enabled"]:
        return {"skipped": True}

    alerts: list[str] = []
    max_dd = risk_metrics.get("max_drawdown_pct")
    if max_dd is not None and abs(float(max_dd)) >= cfg["max_drawdown_alert_pct"]:
        alerts.append(f"组合回撤 {float(max_dd):+.2f}% 超阈值 {cfg['max_drawdown_alert_pct']:.1f}%")

    ir = None
    if daily_totals:
        from agent_reach.daily_run.weekly_card_metrics import build_weekly_risk_metrics

        # reuse benchmark returns via nested import pattern — compute IR from closes if available
        closes = []
        for row in daily_totals:
            total = row.get("total") or row.get("nav")
            try:
                closes.append(float(total))
            except (TypeError, ValueError):
                continue
        daily_rets = _daily_returns(closes)
        bench = risk_metrics.get("benchmark") or {}
        bench_vol = bench.get("volatility_ann_pct")
        port_vol = risk_metrics.get("volatility_ann_pct")
        if daily_rets and port_vol and bench_vol:
            # proxy IR when benchmark daily series unavailable
            ir = round(
                (statistics.mean(daily_rets) * 252) / max(statistics.pstdev(daily_rets), 1e-6) * math.sqrt(252) / 100,
                3,
            )
    if ir is not None and ir < cfg["min_information_ratio"]:
        alerts.append(f"Information Ratio {ir:.2f} 低于阈值 {cfg['min_information_ratio']:.2f}")

    return {
        "skipped": False,
        "alerts": alerts,
        "information_ratio": ir,
        "max_drawdown_pct": max_dd,
        "volatility_ann_pct": risk_metrics.get("volatility_ann_pct"),
        "win_rate_pct": risk_metrics.get("win_rate_pct"),
        "benchmark": risk_metrics.get("benchmark"),
    }


def merge_risk_panel_into_metrics(
    risk_metrics: dict[str, Any],
    *,
    daily_totals: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    panel = build_risk_panel(
        risk_metrics=risk_metrics,
        daily_totals=daily_totals,
        settings=settings,
    )
    merged = dict(risk_metrics)
    merged["risk_panel"] = panel
    return merged


def render_risk_panel_markdown(panel: dict[str, Any]) -> str:
    if panel.get("skipped"):
        return ""
    lines = ["## Risk Panel", ""]
    if panel.get("information_ratio") is not None:
        lines.append(f"- Information Ratio：**{panel['information_ratio']}**")
    if panel.get("max_drawdown_pct") is not None:
        lines.append(f"- Max Drawdown：**{float(panel['max_drawdown_pct']):+.2f}%**")
    if panel.get("volatility_ann_pct") is not None:
        lines.append(f"- Ann. Vol：**{float(panel['volatility_ann_pct']):.2f}%**")
    for alert in panel.get("alerts") or []:
        lines.append(f"- ⚠️ {alert}")
    if len(lines) == 2:
        lines.append("- 无额外风险告警")
    return "\n".join(lines)


def risk_panel_close_blurb(
    panel: dict[str, Any],
    *,
    portfolio_summary: Optional[dict[str, Any]] = None,
) -> str:
    if panel.get("skipped"):
        return ""
    alerts = panel.get("alerts") or []
    if alerts:
        return alerts[0][:160]
    cash = (portfolio_summary or {}).get("cash_ratio")
    if cash is not None:
        return f"Risk panel：现金 {float(cash):.0%}，回撤 {panel.get('max_drawdown_pct', '—')}%"
    return "Risk panel：指标正常"
