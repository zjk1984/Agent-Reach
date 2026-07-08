# -*- coding: utf-8 -*-
"""Build daily-run snapshots from portfolio config + live quotes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def default_portfolio_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "portfolio.json"


def example_portfolio_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "daily_run_portfolio.example.json"


def load_portfolio(path: Optional[Path] = None) -> dict[str, Any]:
    """Load portfolio JSON; user file → example fallback."""
    p = path or default_portfolio_path()
    if not p.exists():
        example = example_portfolio_path()
        if example.exists():
            return json.loads(example.read_text(encoding="utf-8"))
        raise FileNotFoundError(
            f"未找到持仓配置：{p}。可复制 config/daily_run_portfolio.example.json 到该路径"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def save_portfolio(portfolio: dict[str, Any], path: Optional[Path] = None) -> Path:
    p = path or default_portfolio_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(portfolio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def code_to_xueqiu_symbol(code: str) -> str:
    text = code.strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            return text
    text = text.zfill(6)
    if text.startswith(("5", "6", "9")):
        return f"SH{text}"
    if text.startswith(("4", "8")):
        return f"BJ{text}"
    return f"SZ{text}"


def fetch_live_quote(code: str, config=None) -> dict[str, Any]:
    """Fetch quote via Xueqiu (preferred) with AKShare fallback."""
    symbol = code_to_xueqiu_symbol(code)
    xq_error: Optional[str] = None
    try:
        from agent_reach.channels import xueqiu as xq_mod

        xq_mod._ensure_cookies()
        channel = xq_mod.XueqiuChannel()
        q = channel.get_stock_quote(symbol)
        price = q.get("current")
        if price is not None:
            return {
                "code": code.zfill(6)[-6:] if code.isdigit() else code,
                "name": q.get("name", code),
                "price": float(price),
                "change_pct": float(q.get("percent") or 0),
                "reference_price": float(q.get("last_close") or price),
                "source": "xueqiu",
            }
    except Exception as exc:
        xq_error = str(exc)

    try:
        from agent_reach.daily_run.akshare_adapter import fetch_quote, fetch_technicals

        quote = fetch_quote(code)
        technicals = fetch_technicals(code)
        return {**quote, **technicals, "source": "akshare"}
    except Exception as ak_exc:
        msg = f"Xueqiu: {xq_error}; AKShare: {ak_exc}" if xq_error else str(ak_exc)
        raise RuntimeError(f"无法获取 {code} 行情：{msg}") from ak_exc


def enrich_holding(holding: dict[str, Any], config=None) -> dict[str, Any]:
    """Merge live quote into a holding entry."""
    code = str(holding.get("code", ""))
    out = dict(holding)
    try:
        quote = fetch_live_quote(code, config)
        out["price"] = quote["price"]
        out["change_pct"] = quote.get("change_pct")
        out["name"] = quote.get("name") or out.get("name")
        if quote.get("ma20") is not None:
            out["ma20"] = quote["ma20"]
        if quote.get("position_20d") is not None:
            out["position_20d"] = quote["position_20d"]
        if quote.get("volume_ratio") is not None:
            out["volume_ratio"] = quote["volume_ratio"]
        out["quote_source"] = quote.get("source")
    except RuntimeError:
        if out.get("cost") is not None:
            out["price"] = out["cost"]
            out["quote_source"] = "cost_fallback"
    return out


def build_snapshot(
    portfolio: Optional[dict[str, Any]] = None,
    *,
    report_type: str = "intraday",
    primary_code: Optional[str] = None,
    config=None,
    enrich: bool = True,
) -> dict[str, Any]:
    """Build a daily-run snapshot from portfolio config + optional live quotes."""
    pf = portfolio or load_portfolio()
    code = primary_code or pf.get("primary_code") or "MARKET"
    if code == "MARKET" and pf.get("holdings"):
        code = str(pf["holdings"][0]["code"])

    holdings = [dict(h) for h in (pf.get("holdings") or [])]
    watchlist = [dict(w) for w in (pf.get("watchlist") or [])]

    primary_name = code
    primary_price = None
    primary_ma20 = None
    primary_pos = None
    primary_vol = None
    quote_summary_parts: list[str] = []

    if enrich:
        enriched_holdings = []
        for h in holdings:
            eh = enrich_holding(h, config)
            enriched_holdings.append(eh)
            if str(eh.get("code")) == str(code).zfill(6)[-6:] or str(eh.get("code")) == code:
                primary_name = eh.get("name", code)
                primary_price = eh.get("price")
                primary_ma20 = eh.get("ma20")
                primary_pos = eh.get("position_20d")
                primary_vol = eh.get("volume_ratio")
            if eh.get("price") is not None:
                chg = eh.get("change_pct")
                chg_s = f" {chg:+.2f}%" if chg is not None else ""
                quote_summary_parts.append(f"{eh.get('name')} {eh['price']}{chg_s}")
        holdings = enriched_holdings

        enriched_watch = []
        for w in watchlist:
            ew = enrich_holding(w, config)
            enriched_watch.append(ew)
            if ew.get("price") is not None:
                chg = ew.get("change_pct")
                chg_s = f" {chg:+.2f}%" if chg is not None else ""
                quote_summary_parts.append(f"{ew.get('name')} {ew['price']}{chg_s}")
        watchlist = enriched_watch

    portfolio_block = {
        "total": pf.get("total"),
        "cash_ratio": pf.get("cash_ratio"),
        "cash": pf.get("cash"),
        "holdings": holdings,
    }

    sources = dict(pf.get("sources_overrides") or {})
    if quote_summary_parts:
        sources.setdefault("quote", {})["summary"] = " · ".join(quote_summary_parts[:4])
        sources["quote"]["backend"] = "snapshot_builder"
    sources.setdefault("flow", {"summary": "待更新"})
    sources.setdefault("sentiment", {"summary": "待更新"})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "report_type": report_type,
        "code": code.zfill(6)[-6:] if str(code).isdigit() else code,
        "name": primary_name if report_type != "premarket" else f"{today} 早盘",
        "mss_breakdown": dict(pf.get("mss_breakdown") or {}),
        "mss_range": pf.get("mss_range"),
        "sources": sources,
        "structured_review_complete": primary_ma20 is not None,
        "macro_summary": pf.get("macro_summary"),
        "portfolio": portfolio_block,
        "watchlist": watchlist,
    }

    if primary_price is not None:
        snapshot["price"] = primary_price
        snapshot["reference_price"] = primary_price
    if primary_ma20 is not None:
        snapshot["ma20"] = primary_ma20
    if primary_pos is not None:
        snapshot["position_20d"] = primary_pos
    if primary_vol is not None:
        snapshot["volume_ratio"] = primary_vol

    return snapshot


def build_and_save(
    output: Optional[Path] = None,
    *,
    report_type: str = "intraday",
    config=None,
) -> tuple[dict[str, Any], Path]:
    """Build snapshot and write to ~/.agent-reach/daily_run/last_snapshot.json."""
    snap = build_snapshot(report_type=report_type, config=config)
    out = output or (Path.home() / ".agent-reach" / "daily_run" / "last_snapshot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snap, out
