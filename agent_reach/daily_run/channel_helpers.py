# -*- coding: utf-8
"""Channel-backed enrichment for expert plugins."""

from __future__ import annotations

from typing import Any, Optional


def search_exa_snippet(query: str, settings: dict[str, Any]) -> Optional[str]:
    cfg = settings.get("plugins", {})
    if not cfg.get("channel_enrich", True):
        return None
    max_q = int(cfg.get("max_exa_queries_per_expert", 1))
    if max_q <= 0:
        return None
    try:
        from agent_reach.daily_run.exa_client import summarize_hits, web_search_exa

        hits = web_search_exa(query, num_results=2, timeout=int(cfg.get("exa_timeout", 30)))
        return summarize_hits(hits) or None
    except Exception:
        return None


def fetch_xueqiu_hot_summary(limit: int = 3) -> Optional[str]:
    try:
        from agent_reach.channels import xueqiu as xq_mod

        xq_mod._ensure_cookies()
        ch = xq_mod.XueqiuChannel()
        posts = ch.get_hot_posts(limit=limit)
        if not posts:
            return None
        parts = [p.get("title") or p.get("text", "")[:40] for p in posts[:limit]]
        return "雪球：" + " | ".join(p for p in parts if p)
    except Exception:
        return None


def score_from_text(text: str, base: float = 50.0) -> float:
    """Heuristic sentiment score from text keywords."""
    if not text:
        return base
    t = text.lower()
    pos = sum(1 for w in ("涨", "流入", "利好", "突破", "growth", "beat", "surge") if w in t)
    neg = sum(1 for w in ("跌", "流出", "利空", "暴跌", "risk", "miss", "drop", "制裁") if w in t)
    return max(0.0, min(100.0, base + (pos - neg) * 4))
