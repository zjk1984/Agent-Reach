# -*- coding: utf-8
"""Eastmoney clist breadth — up/down/limit approximations when akshare pools are empty."""

from __future__ import annotations

from typing import Any, Optional

_LIMIT_UP_PCT = 9.8


def eastmoney_breadth_fallback_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    """Whether intraday/MR may fall back to Eastmoney clist for market width."""
    from agent_reach.daily_run.settings import effective_settings, load_settings

    cfg = effective_settings(settings or load_settings())
    mr_ok = (cfg.get("market_review") or {}).get("eastmoney_breadth_fallback", True) is not False
    intra_ok = (
        (cfg.get("tsp_quant") or {}).get("intraday") or {}
    ).get("eastmoney_breadth_fallback", True) is not False
    return mr_ok and intra_ok


def _row_limit_up_stock(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("code") or "").zfill(6)
    try:
        change_pct = float(row.get("change_pct") or 0)
    except (TypeError, ValueError):
        change_pct = _LIMIT_UP_PCT
    industry = str(row.get("industry") or "").strip()
    return {
        "code": code,
        "name": str(row.get("name") or code).strip(),
        "change_pct": change_pct,
        "industry": industry or "其他",
        "source": "eastmoney_clist",
    }


def fetch_eastmoney_breadth_pool(
    *,
    settings: Optional[dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """Build akshare-aligned breadth payload from Eastmoney clist + analyze_emotion."""
    from agent_reach.daily_run import eastmoney_market as em
    from agent_reach.daily_run.market_breadth_collector import analyze_emotion
    from agent_reach.daily_run.settings import effective_settings, load_settings

    cfg = effective_settings(settings or load_settings())
    mr_cfg = cfg.get("market_review") or {}
    fetch_timeout = float(
        timeout if timeout is not None else mr_cfg.get("fetch_timeout_seconds", 15)
    )
    akshare_ttl = int((cfg.get("akshare") or {}).get("spot_ttl", 60))

    stocks, stock_source, warnings = em.fetch_all_stocks_resilient(
        timeout=fetch_timeout,
        akshare_ttl=akshare_ttl,
    )
    if not stocks:
        raise RuntimeError("eastmoney clist 返回空列表")

    north, north_warnings = em.fetch_north_flow_resilient(timeout=fetch_timeout)
    warnings.extend(north_warnings)

    emotion = analyze_emotion(stocks, north, settings=cfg)
    em_dict = emotion.to_dict()
    limit_up_stocks = [
        _row_limit_up_stock(s)
        for s in stocks
        if float(s.get("change_pct") or 0) >= _LIMIT_UP_PCT
    ]

    if stock_source == "eastmoney":
        source = "eastmoney_clist"
    else:
        source = f"eastmoney_clist+{stock_source}"

    return {
        "limit_up": int(em_dict.get("limit_up") or 0),
        "limit_down": int(em_dict.get("limit_down") or 0),
        "broken_count": int(em_dict.get("broken_count") or 0),
        "broken_rate": float(em_dict.get("broken_rate") or 0.0),
        "up_count": int(em_dict.get("up_count") or 0),
        "down_count": int(em_dict.get("down_count") or 0),
        "flat_count": int(em_dict.get("flat_count") or 0),
        "limit_up_stocks": limit_up_stocks,
        "source": source,
        "breadth_degraded": stock_source != "eastmoney",
        "limit_degraded": True,
        "ladder_degraded": True,
        "warnings": warnings,
    }


def merge_akshare_pool_enrichment(
    em_pool: dict[str, Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Prefer akshare limit pools for ladder/broken stats after Eastmoney width fill."""
    out = dict(em_pool)
    pool_up = int(pool.get("limit_up") or 0)
    pool_down = int(pool.get("limit_down") or 0)
    pool_broken = int(pool.get("broken_count") or 0)
    pool_stocks = list(pool.get("limit_up_stocks") or [])

    if pool_up + pool_down + pool_broken > 0:
        if pool_up > 0:
            out["limit_up"] = pool_up
        if pool_down > 0:
            out["limit_down"] = pool_down
        if pool_broken > 0:
            out["broken_count"] = pool_broken
            out["broken_rate"] = float(pool.get("broken_rate") or out.get("broken_rate") or 0.0)
            out["limit_degraded"] = False

    if pool_stocks:
        out["limit_up_stocks"] = pool_stocks
        out["ladder_degraded"] = False

    pool_up_count = int(pool.get("up_count") or 0)
    pool_down_count = int(pool.get("down_count") or 0)
    if pool_up_count + pool_down_count > 0:
        out["up_count"] = pool_up_count
        out["down_count"] = pool_down_count
        out["flat_count"] = int(pool.get("flat_count") or out.get("flat_count") or 0)

    em_src = str(out.get("source") or "eastmoney_clist")
    pool_src = str(pool.get("source") or "")
    if pool_src:
        out["source"] = f"{em_src}+{pool_src}" if em_src else pool_src
    return out


def format_breadth_source_label(breadth: dict[str, Any]) -> str:
    """Human-readable provenance strip for panel / Feishu."""
    src = str(breadth.get("source") or "unknown")
    parts: list[str] = []
    if "eastmoney" in src:
        parts.append("东财宽度")
    if "akshare" in src:
        parts.append("akshare池")
    if "xueqiu" in src or "breadth_source" in breadth:
        parts.append("雪球宽度")
    if "market_review" in src:
        parts.append("MR缓存")
    if breadth.get("ladder_degraded"):
        parts.append("连板降级")
    if breadth.get("limit_degraded"):
        parts.append("涨跌停近似")
    return " · ".join(parts) if parts else src
