# -*- coding: utf-8
"""TTL cache for Exa / mcporter web searches."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.exa_client import ExaError, web_search_exa


def exa_cache_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "exa_cache"


def _cache_key(query: str, num_results: int) -> str:
    raw = f"{query.strip().lower()}|{num_results}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return exa_cache_dir() / f"{key}.json"


def get_cached_search(query: str, *, num_results: int = 3, ttl_seconds: int = 86400) -> Optional[list[dict[str, Any]]]:
    key = _cache_key(query, num_results)
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - float(data.get("ts") or 0) > ttl_seconds:
        return None
    hits = data.get("hits")
    return hits if isinstance(hits, list) else None


def put_cached_search(query: str, hits: list[dict[str, Any]], *, num_results: int = 3) -> None:
    exa_cache_dir().mkdir(parents=True, exist_ok=True)
    key = _cache_key(query, num_results)
    _cache_path(key).write_text(
        json.dumps({"query": query, "ts": time.time(), "hits": hits}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cached_web_search_exa(
    query: str,
    *,
    num_results: int = 3,
    timeout: int = 45,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (hits, from_cache)."""
    cfg = (settings or {}).get("exa_cache") or {}
    if cfg.get("enabled", True) is False:
        return web_search_exa(query, num_results=num_results, timeout=timeout), False

    ttl = int(cfg.get("ttl_seconds", 86400))
    cached = get_cached_search(query, num_results=num_results, ttl_seconds=ttl)
    if cached is not None:
        return cached, True

    hits = web_search_exa(query, num_results=num_results, timeout=timeout)
    put_cached_search(query, hits, num_results=num_results)
    return hits, False
