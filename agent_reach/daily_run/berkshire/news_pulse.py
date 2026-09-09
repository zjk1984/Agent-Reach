# -*- coding: utf-8
"""News pulse lite — watchlist drawdown attribution + thesis re-review flag."""

from __future__ import annotations

from typing import Any, Optional


def news_pulse_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("news_pulse") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "min_severity": str(block.get("min_severity") or "yellow"),
        "exa_enabled": block.get("exa_enabled", True) is not False,
        "eastmoney_enabled": block.get("eastmoney_enabled", True) is not False,
        "eastmoney_limit": max(1, int(block.get("eastmoney_limit", 3))),
        "thesis_review_on_red": block.get("thesis_review_on_red", True) is not False,
    }


def _severity_rank(severity: str) -> int:
    return {"yellow": 1, "red": 2}.get(str(severity or ""), 0)


def collect_news_pulse_targets(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.session_verdict_guards import collect_watchlist_drawdown_alerts

    cfg = news_pulse_cfg(settings)
    if not cfg.get("enabled", True):
        return []
    min_rank = _severity_rank(cfg["min_severity"])
    alerts = collect_watchlist_drawdown_alerts(portfolio, settings=settings)
    return [a for a in alerts if _severity_rank(str(a.get("severity") or "")) >= min_rank]


def _fetch_eastmoney(name: str, code: str, *, limit: int) -> list[dict[str, Any]]:
    try:
        from agent_reach.daily_run.eastmoney_intent import search_eastmoney_news

        keyword = f"{name} {code}".strip()
        return search_eastmoney_news(keyword, limit=limit)
    except Exception:
        return []


def _fetch_exa(name: str, code: str, *, settings: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = news_pulse_cfg(settings)
    if not cfg.get("exa_enabled", True):
        return []
    try:
        from agent_reach.daily_run.exa_cache import cached_web_search_exa

        query = f"{name} {code} China A-share stock news catalyst reason drop 2026"
        hits, _cached = cached_web_search_exa(
            query,
            num_results=3,
            timeout=int(((settings or {}).get("plugins") or {}).get("exa_timeout", 45)),
            settings=settings,
        )
        return hits if isinstance(hits, list) else []
    except Exception:
        return []


def run_news_pulse_lite(
    alert: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    name = str(alert.get("name") or alert.get("code") or "")
    code = str(alert.get("code") or "")
    cfg = news_pulse_cfg(settings)
    eastmoney = (
        _fetch_eastmoney(name, code, limit=int(cfg["eastmoney_limit"]))
        if cfg.get("eastmoney_enabled", True)
        else []
    )
    exa_hits = _fetch_exa(name, code, settings=settings)
    thesis_review = bool(
        cfg.get("thesis_review_on_red", True) and str(alert.get("severity") or "") == "red"
    )
    primary_cause = ""
    if eastmoney:
        primary_cause = str(eastmoney[0].get("title") or eastmoney[0].get("content") or "")[:120]
    elif exa_hits:
        primary_cause = str(exa_hits[0].get("title") or exa_hits[0].get("snippet") or "")[:120]

    return {
        "code": code,
        "name": name,
        "alert": alert,
        "eastmoney": eastmoney,
        "exa_hits": exa_hits,
        "primary_cause": primary_cause,
        "thesis_review": thesis_review,
    }


def run_news_pulse_batch(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    max_symbols: int = 3,
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled

    if not berkshire_enabled(settings, key="news_pulse"):
        return []
    targets = collect_news_pulse_targets(portfolio, settings=settings)
    results: list[dict[str, Any]] = []
    for alert in targets[: max(1, max_symbols)]:
        results.append(run_news_pulse_lite(alert, settings=settings))
    return results


def render_news_pulse_markdown(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["**📡 新闻脉搏（news-pulse lite）**", ""]
    for row in results:
        alert = row.get("alert") or {}
        icon = "🔴" if alert.get("severity") == "red" else "🟡"
        name = row.get("name") or row.get("code")
        lines.append(f"### {icon} {name} · {alert.get('text', '')}")
        if row.get("primary_cause"):
            lines.append(f"- **异动主因（初判）：** {row['primary_cause']}")
        for item in (row.get("eastmoney") or [])[:2]:
            title = str(item.get("title") or item.get("content") or "")[:80]
            if title:
                lines.append(f"- 东财：{title}")
        for hit in (row.get("exa_hits") or [])[:2]:
            title = str(hit.get("title") or hit.get("url") or "")[:80]
            if title:
                lines.append(f"- Exa：{title}")
        if row.get("thesis_review"):
            lines.append("- **🔄 建议触发投资论文重审**（thesis-tracker / thesis-drift）")
        lines.append("")
    return "\n".join(lines).strip()
