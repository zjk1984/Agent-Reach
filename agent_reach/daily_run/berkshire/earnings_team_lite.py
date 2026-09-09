# -*- coding: utf-8
"""Earnings team lite — four-perspective close research for top holdings."""

from __future__ import annotations

from typing import Any, Optional

_PERSPECTIVES: tuple[tuple[str, str, str], ...] = (
    ("duan", "段永平·生意", "business model moat pricing power"),
    ("buffett", "巴菲特·财务", "earnings quality balance sheet valuation"),
    ("munger", "芒格·竞争", "industry competition market share"),
    ("li", "李录·风险", "risk management governance red flags"),
)


def earnings_team_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("earnings_team_lite") or {})
    plugins = (settings or {}).get("plugins") or {}
    return {
        "enabled": block.get("enabled", True) is not False,
        "max_holdings": max(1, int(block.get("max_holdings", 3))),
        "num_results": max(1, int(block.get("num_results", 2))),
        "timeout": int(block.get("timeout") or plugins.get("exa_timeout", 45)),
        "prefer_over_exa_research": block.get("prefer_over_exa_research", True) is not False,
        "max_queries": max(1, int(block.get("max_queries", 6))),
    }


def _holding_targets(snapshot: dict[str, Any], *, max_holdings: int) -> list[dict[str, Any]]:
    holdings = list((snapshot.get("portfolio") or {}).get("holdings") or [])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in holdings:
        code = str(row.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": str(row.get("name") or code),
                "type": "holding",
            }
        )
        if len(out) >= max_holdings:
            break
    return out


def _run_perspective_query(
    target: dict[str, Any],
    master_key: str,
    label: str,
    angle: str,
    *,
    settings: Optional[dict[str, Any]],
    num_results: int,
    timeout: int,
) -> dict[str, Any]:
    name = target.get("name") or target.get("code")
    code = target.get("code") or ""
    query = f"{name} {code} latest earnings report {angle} 2026"
    try:
        from agent_reach.daily_run.exa_cache import cached_web_search_exa
        from agent_reach.daily_run.exa_client import summarize_hits

        hits, _cached = cached_web_search_exa(
            query,
            num_results=num_results,
            timeout=timeout,
            settings=settings,
        )
        return {
            "master": master_key,
            "label": label,
            "query": query,
            "hits": hits,
            "summary": summarize_hits(hits),
            "success": True,
        }
    except Exception as exc:
        from agent_reach.daily_run.exa_client import format_exa_error

        msg = format_exa_error(str(exc))
        return {
            "master": master_key,
            "label": label,
            "query": query,
            "hits": [],
            "summary": msg,
            "success": False,
        }


def run_earnings_team_lite(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.exa_client import is_exa_available

    cfg = earnings_team_cfg(settings)
    if not cfg.get("enabled", True) or not is_exa_available():
        return []

    targets = _holding_targets(snapshot, max_holdings=int(cfg["max_holdings"]))
    if not targets:
        return []

    budget = int(cfg["max_queries"])
    results: list[dict[str, Any]] = []
    for target in targets:
        perspectives: list[dict[str, Any]] = []
        for master_key, label, angle in _PERSPECTIVES:
            if budget <= 0:
                break
            perspectives.append(
                _run_perspective_query(
                    target,
                    master_key,
                    label,
                    angle,
                    settings=settings,
                    num_results=int(cfg["num_results"]),
                    timeout=int(cfg["timeout"]),
                )
            )
            budget -= 1
        if not perspectives:
            break
        results.append(
            {
                "code": target.get("code"),
                "name": target.get("name"),
                "perspectives": perspectives,
                "success": any(p.get("success") for p in perspectives),
            }
        )
    return results


def earnings_team_as_research_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten four-master rows into the Exa research_results shape used by report_audit."""
    out: list[dict[str, Any]] = []
    for row in results:
        for perspective in row.get("perspectives") or []:
            out.append(
                {
                    "success": bool(perspective.get("success")),
                    "query": perspective.get("query"),
                    "target": {
                        "code": row.get("code"),
                        "name": row.get("name"),
                        "master": perspective.get("master"),
                    },
                    "hits": perspective.get("hits") or [],
                    "summary": perspective.get("summary"),
                }
            )
    return out


def earnings_team_has_success(results: list[dict[str, Any]]) -> bool:
    return any(row.get("success") for row in results)


def render_earnings_team_markdown(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["**📊 财报精读团队 lite（四大师视角）**", ""]
    for row in results:
        name = row.get("name") or row.get("code")
        lines.append(f"### {name}")
        for perspective in row.get("perspectives") or []:
            status = "✅" if perspective.get("success") else "⚠️"
            label = perspective.get("label") or perspective.get("master")
            summary = perspective.get("summary") or "—"
            lines.append(f"- {status} **{label}：** {summary[:100]}")
        lines.append("")
    return "\n".join(lines).strip()
