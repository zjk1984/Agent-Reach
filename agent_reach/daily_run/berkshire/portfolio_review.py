# -*- coding: utf-8
"""Portfolio review lite — concentration & watchlist health (ROADMAP P2)."""

from __future__ import annotations

from typing import Any, Optional


def portfolio_review_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("portfolio_review") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "max_single_position_pct": float(block.get("max_single_position_pct", 35.0)),
        "max_watchlist_size": int(block.get("max_watchlist_size", 10)),
    }


def review_portfolio(portfolio: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled

    cfg = portfolio_review_cfg(settings)
    if not berkshire_enabled(settings, key="portfolio_review") or not cfg.get("enabled", True):
        return {"skipped": True}

    holdings = list(portfolio.get("holdings") or [])
    watchlist = list(portfolio.get("watchlist") or [])
    warnings: list[str] = []

    total_value = 0.0
    for row in holdings:
        shares = float(row.get("shares") or 0)
        price = float(row.get("price") or row.get("last_price") or 0)
        total_value += shares * price

    if total_value > 0:
        for row in holdings:
            shares = float(row.get("shares") or 0)
            price = float(row.get("price") or row.get("last_price") or 0)
            pct = shares * price / total_value * 100.0
            if pct > cfg["max_single_position_pct"]:
                name = row.get("name") or row.get("code")
                warnings.append(f"单票集中度 {name} {pct:.1f}% > {cfg['max_single_position_pct']:.0f}%")

    if len(watchlist) > cfg["max_watchlist_size"]:
        warnings.append(f"观察池 {len(watchlist)} 只 > 上限 {cfg['max_watchlist_size']}")

    return {
        "holdings_count": len(holdings),
        "watchlist_count": len(watchlist),
        "warnings": warnings,
        "passed": not warnings,
    }


def render_portfolio_review_markdown(review: dict[str, Any]) -> str:
    if review.get("skipped") or not review.get("warnings"):
        return ""
    lines = ["**📦 组合健康度（portfolio-review lite）**", ""]
    for warning in review.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    return "\n".join(lines)
