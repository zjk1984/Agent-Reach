# -*- coding: utf-8
"""Portfolio-level quote coverage and quote-fetch meta enrichment."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.data_audit_policy import data_audit_cfg
from agent_reach.daily_run.quote_fetch import QuoteFetchResult, normalize_code
from agent_reach.daily_run.symbols import build_enriched_symbols, portfolio_from_snapshot


def _merged_portfolio_rows(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("holdings", "watchlist"):
        for row in portfolio.get(bucket) or []:
            code = normalize_code(str(row.get("code") or ""))
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(dict(row))
    return rows


def symbol_has_live_quote(row: dict[str, Any], enriched: dict[str, dict[str, Any]]) -> bool:
    code = normalize_code(str(row.get("code") or ""))
    merged = {**row, **enriched.get(code, {})}
    if merged.get("quote_source") == "cost_fallback":
        return False
    price = merged.get("price")
    if price is None:
        return False
    source = str(merged.get("quote_source") or merged.get("source") or "").strip()
    if source and source not in {"cost_fallback"}:
        return True
    if merged.get("change_pct") is not None:
        return True
    cost = merged.get("cost")
    if cost is not None and float(cost) == float(price):
        return False
    return True


def portfolio_quote_coverage(
    portfolio: dict[str, Any],
    enriched: Optional[dict[str, dict[str, Any]]] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Coverage over merged holdings + watchlist (non-held watchlist included once)."""
    pf = portfolio or {}
    enriched = enriched if enriched is not None else build_enriched_symbols({"portfolio": pf})
    rows = _merged_portfolio_rows(pf)
    if not rows:
        return {
            "symbol_count": 0,
            "quoted_count": 0,
            "coverage_pct": 100.0,
            "missing_codes": [],
            "below_threshold": False,
            "threshold_pct": round(float(data_audit_cfg(settings or {}).get("min_quote_coverage_pct", 0.8)) * 100, 1),
        }

    missing: list[str] = []
    quoted = 0
    for row in rows:
        code = normalize_code(str(row.get("code") or ""))
        if symbol_has_live_quote(row, enriched):
            quoted += 1
        else:
            missing.append(code)

    total = len(rows)
    pct = round(quoted / total * 100, 1)
    threshold_pct = round(float(data_audit_cfg(settings or {}).get("min_quote_coverage_pct", 0.8)) * 100, 1)
    return {
        "symbol_count": total,
        "quoted_count": quoted,
        "coverage_pct": pct,
        "missing_codes": missing,
        "below_threshold": pct < threshold_pct,
        "threshold_pct": threshold_pct,
    }


def portfolio_quote_coverage_for_snapshot(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    pf = portfolio_from_snapshot(snapshot)
    enriched = build_enriched_symbols(snapshot)
    return portfolio_quote_coverage(pf, enriched, settings=settings)


def enrich_quote_fetch_meta(
    meta: dict[str, Any],
    fetch_res: QuoteFetchResult,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach primary vs fallback source markers for manifest visibility."""
    cfg = settings or {}
    order = (cfg.get("quote_fetch") or {}).get("sources") or ["eastmoney", "xueqiu", "akshare"]
    primary = str(order[0]) if order else "eastmoney"
    sources_used = list(meta.get("sources_used") or fetch_res.sources_used or [])
    fallback_sources = [s for s in sources_used if s and s != primary]
    per_code_sources: dict[str, str] = {}
    fallback_codes: list[str] = []
    for code, row in (fetch_res.quotes or {}).items():
        src = str(row.get("source") or row.get("quote_source") or "").strip()
        if src:
            per_code_sources[normalize_code(code)] = src
            if src != primary:
                fallback_codes.append(normalize_code(code))

    out = dict(meta)
    out["primary_source"] = primary
    out["fallback_used"] = bool(fallback_sources or fallback_codes)
    out["fallback_sources"] = list(dict.fromkeys(fallback_sources + [s for s in per_code_sources.values() if s != primary]))
    if fallback_codes:
        out["fallback_codes"] = list(dict.fromkeys(fallback_codes))
    return out


def format_portfolio_quote_coverage_warning(coverage: dict[str, Any]) -> Optional[str]:
    if not coverage or int(coverage.get("symbol_count") or 0) <= 0:
        return None
    pct = float(coverage.get("coverage_pct") or 0)
    quoted = int(coverage.get("quoted_count") or 0)
    total = int(coverage.get("symbol_count") or 0)
    threshold = float(coverage.get("threshold_pct") or 80)
    flag = " ⚠️" if coverage.get("below_threshold") else ""
    line = f"**行情覆盖：** {quoted}/{total}（{pct:.1f}%）"
    if coverage.get("below_threshold"):
        line += f"，低于阈值 {threshold:.0f}%{flag}"
    elif flag:
        line += flag
    missing = coverage.get("missing_codes") or []
    if missing and coverage.get("below_threshold"):
        sample = ", ".join(missing[:5])
        if len(missing) > 5:
            sample += f" 等{len(missing)}只"
        line += f"（缺报价：{sample}）"
    return line
