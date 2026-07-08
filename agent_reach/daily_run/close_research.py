# -*- coding: utf-8
"""Close research via Exa (auto) + query templates (fallback)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.exa_client import ExaError, is_exa_available, summarize_hits, web_search_exa


def build_research_queries(snapshot: dict[str, Any]) -> list[dict[str, str]]:
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


def run_exa_research(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute Exa searches for close review; returns list of {label, query, hits, summary}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cfg = settings.get("plugins", {})
    if not cfg.get("exa_research_on_close", True):
        return []

    max_queries = int(cfg.get("max_exa_queries", 3))
    timeout = int(cfg.get("exa_timeout", 45))

    if not is_exa_available():
        return []

    queries = build_research_queries(snapshot)[:max_queries]
    if not queries:
        return []

    def _run_one(q: dict[str, str]) -> dict[str, Any]:
        try:
            hits = web_search_exa(q["query"], num_results=3, timeout=timeout)
            return {**q, "hits": hits, "summary": summarize_hits(hits), "success": True}
        except ExaError as exc:
            return {**q, "hits": [], "summary": str(exc), "success": False}

    workers = min(max_queries, 3)
    ordered: list[Optional[dict[str, Any]]] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one, q): i for i, q in enumerate(queries)}
        for fut in as_completed(futures):
            ordered[futures[fut]] = fut.result()
    return [r for r in ordered if r is not None]


def render_research_markdown(
    snapshot: dict[str, Any],
    *,
    research_results: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    """Render close research: live Exa results or fallback templates."""
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    results = research_results
    if results is None and cfg.get("plugins", {}).get("exa_research_on_close", True):
        results = run_exa_research(snapshot, cfg)

    queries = build_research_queries(snapshot)
    if not queries and not results:
        return ""

    if results and any(r.get("success") for r in results):
        lines = ["**🔍 收盘深度调研（Exa 自动）**", ""]
        for r in results:
            status = "✅" if r.get("success") else "⚠️"
            lines.append(f"### {status} {r.get('label', '调研')}")
            if r.get("summary"):
                lines.append(r["summary"])
            for h in (r.get("hits") or [])[:2]:
                title = h.get("title") or "—"
                url = h.get("url") or ""
                if url:
                    lines.append(f"- [{title[:60]}]({url})")
                else:
                    lines.append(f"- {title[:80]}")
            lines.append("")
        return "\n".join(lines).strip()

    lines = [
        "**🔍 收盘深度调研（Exa 查询模板）**",
        "",
        "Exa 未就绪，可在本地执行：",
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
