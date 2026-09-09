# -*- coding: utf-8
"""AKShare fundamentals enrichment for financial_rigor (ai-berkshire inspired)."""

from __future__ import annotations

from typing import Any, Optional


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enrich_snapshot_for_financial_rigor(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Best-effort fill price/shares/market_cap from AKShare spot for rigor checks."""
    out = dict(snapshot)
    code = str(out.get("code") or "").strip()
    if not code:
        return out

    try:
        from agent_reach.daily_run.akshare_adapter import fetch_quote
    except ImportError:
        return out

    try:
        quote = fetch_quote(code, ttl=120)
    except Exception:
        return out

    price = _optional_float(out.get("price")) or _optional_float(quote.get("price"))
    market_cap = _optional_float(out.get("market_cap") or out.get("market_capital"))
    cap_from_quote = _optional_float(quote.get("market_capital"))
    if market_cap is None and cap_from_quote is not None:
        market_cap = cap_from_quote
        out["market_capital"] = cap_from_quote
        out["market_cap"] = cap_from_quote

    # Do not derive shares from the same market_cap we later verify — that is tautological.
    if market_cap and market_cap > 0:
        out.setdefault("total_market_cap", market_cap)

    pe = _optional_float(quote.get("pe_ttm"))
    if pe and pe > 0 and price:
        eps = price / pe
        out.setdefault("eps_ttm", eps)

    out.setdefault("fundamentals_source", "akshare_spot_em")
    return out
