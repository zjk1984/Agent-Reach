# -*- coding: utf-8
"""Close research queries (Exa-ready templates)."""

from __future__ import annotations

from typing import Any


def build_research_queries(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Build research query list from holdings + watchlist."""
    queries: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in (snapshot.get("portfolio") or {}).get("holdings") or []:
        name = item.get("name") or item.get("code")
        code = item.get("code", "")
        if not name:
            continue
        key = str(code)
        if key in seen:
            continue
        seen.add(key)
        queries.append({
            "type": "holding",
            "query": f"{name} {code} latest earnings financial report 2026",
            "label": f"{name} 财报",
        })

    for item in snapshot.get("watchlist") or []:
        name = item.get("name") or item.get("code")
        code = item.get("code", "")
        key = str(code)
        if not name or key in seen:
            continue
        seen.add(key)
        queries.append({
            "type": "watchlist",
            "query": f"{name} {code} industry competitors market share 2026",
            "label": f"{name} 竞品",
        })

    if snapshot.get("industry") or snapshot.get("sector"):
        sector = snapshot.get("industry") or snapshot.get("sector")
        queries.append({
            "type": "industry",
            "query": f"{sector} supply chain outlook China A-share 2026",
            "label": f"{sector} 行业",
        })

    return queries[:6]


def render_research_markdown(snapshot: dict[str, Any]) -> str:
    """Render close research section (query templates for Exa / manual)."""
    queries = build_research_queries(snapshot)
    if not queries:
        return ""

    lines = [
        "**🔍 收盘深度调研（Exa 查询模板）**",
        "",
        "可在本地执行：",
        "```bash",
    ]
    for q in queries[:4]:
        lines.append(
            f'mcporter call \'exa.web_search_exa(query: "{q["query"]}", numResults: 5)\''
        )
    lines.append("```")
    lines.extend(["", "**调研清单：**"])
    for q in queries:
        lines.append(f"- {q['label']}")
    return "\n".join(lines)
