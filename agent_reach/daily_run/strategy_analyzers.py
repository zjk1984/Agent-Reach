# -*- coding: utf-8
"""Standard strategy analyzers (Backtrader addanalyzer-style metrics)."""

from __future__ import annotations

from typing import Any, Optional


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze_equity_curve(daily_totals: list[dict[str, Any]]) -> dict[str, Any]:
    """Max drawdown and period return from daily total snapshots."""
    points: list[tuple[str, float]] = []
    for row in daily_totals or []:
        if not isinstance(row, dict):
            continue
        total = _optional_float(row.get("total"))
        day = str(row.get("date") or "")[:10]
        if total is not None and day:
            points.append((day, total))
    if len(points) < 2:
        return {}
    points.sort(key=lambda x: x[0])
    start = points[0][1]
    end = points[-1][1]
    peak = points[0][1]
    max_dd = 0.0
    max_dd_day = points[0][0]
    for day, total in points:
        peak = max(peak, total)
        if peak > 0:
            dd = (peak - total) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
                max_dd_day = day
    ret_pct = ((end - start) / start * 100.0) if start else None
    return {
        "period_return_pct": round(ret_pct, 2) if ret_pct is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_day": max_dd_day,
        "start_total": round(start, 2),
        "end_total": round(end, 2),
        "observation_days": len(points),
    }


def analyze_trade_profit_factor(trade_pnl_detail: dict[str, Any]) -> dict[str, Any]:
    wins: list[float] = []
    losses: list[float] = []
    for sell in trade_pnl_detail.get("sells") or []:
        if not isinstance(sell, dict):
            continue
        pnl = _optional_float(sell.get("realized_pnl"))
        if pnl is None:
            continue
        if pnl >= 0:
            wins.append(pnl)
        else:
            losses.append(abs(pnl))
    profit_factor = None
    if wins and losses:
        profit_factor = round(sum(wins) / sum(losses), 2)
    return {
        "profit_factor": profit_factor,
        "win_trade_count": len(wins),
        "loss_trade_count": len(losses),
        "gross_profit": round(sum(wins), 2) if wins else 0.0,
        "gross_loss": round(sum(losses), 2) if losses else 0.0,
    }


def build_strategy_analyzers(
    *,
    daily_totals: list[dict[str, Any]],
    trade_pnl_detail: dict[str, Any],
) -> dict[str, Any]:
    equity = analyze_equity_curve(daily_totals)
    pf = analyze_trade_profit_factor(trade_pnl_detail)
    if not equity and not pf.get("profit_factor"):
        return {}
    return {"equity": equity, "trades": pf}


def merge_analyzers_into_validation(
    validation: dict[str, Any],
    analyzers: dict[str, Any],
) -> dict[str, Any]:
    if not analyzers:
        return validation
    out = dict(validation)
    out["analyzers"] = analyzers
    equity = analyzers.get("equity") or {}
    trades = analyzers.get("trades") or {}
    if equity.get("max_drawdown_pct") is not None:
        out["max_drawdown_pct"] = equity["max_drawdown_pct"]
    if trades.get("profit_factor") is not None:
        out["profit_factor"] = trades["profit_factor"]
    suggestions = list(out.get("suggestions") or [])
    dd = equity.get("max_drawdown_pct")
    if dd is not None and float(dd) >= 8.0:
        suggestions.insert(0, f"区间最大回撤 {float(dd):.1f}%，建议检查仓位与卖出规则")
    pf = trades.get("profit_factor")
    if pf is not None and float(pf) < 1.0:
        suggestions.append(f"Profit Factor {float(pf):.2f} < 1，盈亏比需优化")
    out["suggestions"] = suggestions[:3]
    return out
