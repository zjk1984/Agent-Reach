# -*- coding: utf-8
"""Multi-platform hot news via 60s API (self-hosted or public instance)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run")

# 60s v2 routes — see https://github.com/vikiboss/60s
PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "60s": {"path": "/v2/60s", "kind": "daily"},
    "weibo": {"path": "/v2/weibo", "kind": "list"},
    "zhihu": {"path": "/v2/zhihu", "kind": "list"},
    "douyin": {"path": "/v2/douyin", "kind": "list"},
    "toutiao": {"path": "/v2/toutiao", "kind": "list"},
    "bili": {"path": "/v2/bili", "kind": "list"},
    "baidu": {"path": "/v2/baidu/hot", "kind": "list"},
    "it-news": {"path": "/v2/it-news", "kind": "list", "params": {"limit": "15"}},
}

DEFAULT_BASE_URLS = [
    "http://127.0.0.1:8787",
    "https://60s.viki.moe",
]


@dataclass
class HotNewsResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    matched: list[dict[str, Any]] = field(default_factory=list)
    daily_headlines: list[str] = field(default_factory=list)
    daily_tip: str = ""
    daily_date: str = ""
    platforms_ok: list[str] = field(default_factory=list)
    summary: str = ""
    headline_summary: str = ""
    text_feed: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "matched": self.matched,
            "daily_headlines": self.daily_headlines,
            "daily_tip": self.daily_tip,
            "daily_date": self.daily_date,
            "platforms_ok": self.platforms_ok,
            "summary": self.summary,
            "headline_summary": self.headline_summary,
            "text_feed": self.text_feed,
        }


def hot_news_cache_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "cache"


def portfolio_keywords(portfolio: dict[str, Any], settings: Optional[dict[str, Any]] = None) -> list[str]:
    """Keywords from holdings/watchlist + configured sector terms."""
    cfg = (settings or {}).get("hot_news") or {}
    keys: list[str] = []
    seen: set[str] = set()
    for h in portfolio.get("holdings") or []:
        name = str(h.get("name") or "").strip()
        if name:
            token = name[:4]
            if token not in seen:
                seen.add(token)
                keys.append(token)
        code = str(h.get("code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            keys.append(code)
    for w in portfolio.get("watchlist") or []:
        name = str(w.get("name") or "").strip()
        if name:
            token = name[:4]
            if token not in seen:
                seen.add(token)
                keys.append(token)
    for kw in cfg.get("extra_keywords") or ["存储", "芯片", "DDR", "北向", "半导体", "AI", "光通信"]:
        if kw and kw not in seen:
            seen.add(kw)
            keys.append(str(kw))
    return keys


def collect_hot_news(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> HotNewsResult:
    """Fetch hot topics from configured 60s API platforms."""
    cfg = (settings or {}).get("hot_news") or {}
    if cfg.get("enabled") is False:
        return HotNewsResult()

    platforms = list(cfg.get("platforms") or ["60s", "weibo", "zhihu", "it-news"])
    base_urls = list(cfg.get("base_urls") or DEFAULT_BASE_URLS)
    ttl = int(cfg.get("cache_ttl_seconds", 600))
    timeout = int(cfg.get("timeout_seconds", 12))
    limit = int(cfg.get("limit_per_platform", 20))
    match_kw = cfg.get("match_portfolio_keywords", True) is not False
    keywords = portfolio_keywords(portfolio, settings) if match_kw else []

    out = HotNewsResult()
    base_url = _resolve_base_url(base_urls, timeout=timeout)
    if not base_url:
        logger.debug("hot_news: no reachable 60s base_url in {}", base_urls)
        return out

    for platform in platforms:
        spec = PLATFORM_SPECS.get(platform)
        if not spec:
            continue
        try:
            raw = _fetch_platform_cached(
                base_url,
                platform,
                spec,
                ttl_seconds=ttl,
                timeout=timeout,
            )
            items = _normalize_platform(platform, raw, limit=limit)
            out.items.extend(items)
            out.platforms_ok.append(platform)
            if platform == "60s":
                out.daily_headlines = [i["title"] for i in items]
                out.daily_tip = str(raw.get("tip") or "") if isinstance(raw, dict) else ""
                out.daily_date = str(raw.get("date") or "") if isinstance(raw, dict) else ""
        except Exception as exc:
            logger.debug("hot_news {} failed: {}", platform, exc)

    if match_kw and keywords:
        out.matched = [i for i in out.items if _matches_keywords(i.get("title", ""), keywords)]
    else:
        out.matched = out.items[:8]

    out.headline_summary = _format_daily_headlines(out)
    out.summary = _build_summary(out, keywords)
    out.text_feed = render_hot_news_text(out)
    return out


def render_hot_news_text(result: HotNewsResult, *, max_lines: int = 12) -> str:
    """Plain-text block suitable for Feishu / logs."""
    if not result.items and not result.daily_headlines:
        return ""
    lines: list[str] = []
    if result.daily_headlines:
        lines.append(f"📰 60s 今日要闻（{result.daily_date or '今日'}）")
        for i, title in enumerate(result.daily_headlines[:5], 1):
            lines.append(f"  {i}. {title}")
        if result.daily_tip:
            lines.append(f"  微语：{result.daily_tip}")
        lines.append("")
    if result.matched:
        lines.append("🔥 持仓/板块相关热搜")
        for i, item in enumerate(result.matched[:max_lines], 1):
            hot = item.get("hot_value")
            hot_s = f" ({hot})" if hot is not None else ""
            lines.append(f"  {i}. [{item.get('platform')}] {item.get('title')}{hot_s}")
    elif result.items:
        lines.append("🔥 跨平台热搜 Top")
        for i, item in enumerate(result.items[:max_lines], 1):
            lines.append(f"  {i}. [{item.get('platform')}] {item.get('title')}")
    return "\n".join(lines).strip()


def _resolve_base_url(base_urls: list[str], *, timeout: int) -> Optional[str]:
    health_paths = ("/health", "/v2/health")
    for base in base_urls:
        base = base.rstrip("/")
        for hp in health_paths:
            try:
                r = requests.get(f"{base}{hp}", timeout=min(timeout, 5))
                if r.status_code == 200:
                    return base
            except Exception:
                continue
        # Fallback: probe lightweight endpoint
        try:
            r = requests.get(
                f"{base}/v2/60s",
                params={"encoding": "json"},
                timeout=timeout,
            )
            if r.status_code == 200:
                return base
        except Exception:
            continue
    return None


def _fetch_platform_cached(
    base_url: str,
    platform: str,
    spec: dict[str, Any],
    *,
    ttl_seconds: int,
    timeout: int,
) -> Any:
    cache_path = hot_news_cache_dir() / f"hot_news_{platform}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("ts") or 0) <= ttl_seconds:
                return cached.get("data")
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    params = dict(spec.get("params") or {})
    params["encoding"] = "json"
    url = urljoin(base_url + "/", spec["path"].lstrip("/"))
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    data = body.get("data") if isinstance(body, dict) and "data" in body else body

    hot_news_cache_dir().mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"ts": time.time(), "data": data, "platform": platform}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return data


def _normalize_platform(platform: str, raw: Any, *, limit: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    if platform == "60s":
        return _normalize_60s_daily(raw, fetched_at=now, limit=limit)
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for row in raw[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("word") or "").strip()
        if not title:
            continue
        hot_val = row.get("hot_value") or row.get("hot_value_desc") or row.get("score") or row.get("score_desc")
        items.append(
            {
                "title": title,
                "link": row.get("link") or row.get("url") or "",
                "hot_value": hot_val,
                "platform": platform,
                "source": f"60s_api/{platform}",
                "fetched_at": now,
            }
        )
    return items


def _normalize_60s_daily(raw: Any, *, fetched_at: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    news = raw.get("news") or []
    items: list[dict[str, Any]] = []
    for entry in news[:limit]:
        if isinstance(entry, str):
            title = entry.strip()
            link = ""
        elif isinstance(entry, dict):
            title = str(entry.get("title") or "").strip()
            link = str(entry.get("link") or "")
        else:
            continue
        if not title:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "hot_value": None,
                "platform": "60s",
                "source": "60s_api/60s",
                "fetched_at": fetched_at,
            }
        )
    return items


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    text = title.lower()
    for kw in keywords:
        if kw and kw.lower() in text:
            return True
    return False


def _format_daily_headlines(result: HotNewsResult) -> str:
    if not result.daily_headlines:
        return ""
    top = " | ".join(result.daily_headlines[:3])
    prefix = f"今日要闻：{top}"
    if result.daily_tip:
        return f"{prefix}（{result.daily_tip[:24]}）"
    return prefix[:120]


def _build_summary(result: HotNewsResult, keywords: list[str]) -> str:
    parts: list[str] = []
    if result.headline_summary:
        parts.append(result.headline_summary[:80])
    if result.matched:
        hit_titles = [m.get("title", "")[:20] for m in result.matched[:3]]
        parts.append("热搜命中：" + " | ".join(t for t in hit_titles if t))
    elif result.items:
        top = [i.get("title", "")[:18] for i in result.items[:2]]
        parts.append("热搜：" + " | ".join(t for t in top if t))
    if keywords and result.matched:
        parts.append(f"（关键词 {len(keywords)} 个，命中 {len(result.matched)} 条）")
    return "；".join(parts)[:220]
