# -*- coding: utf-8
"""Shared portfolio / symbol helpers for daily-run modules."""

from __future__ import annotations

from typing import Any

from agent_reach.daily_run.snapshot_builder import _normalize_code


def copy_portfolio(portfolio: dict[str, Any]) -> dict[str, Any]:
    pf = dict(portfolio)
    pf["holdings"] = [dict(h) for h in (portfolio.get("holdings") or [])]
    pf["watchlist"] = [dict(w) for w in (portfolio.get("watchlist") or [])]
    return pf


def build_enriched_symbols(
    snapshot: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge holdings + watchlist + primary code from snapshot into one map."""
    out: dict[str, dict[str, Any]] = {}
    for h in (snapshot.get("portfolio") or {}).get("holdings") or []:
        code = _normalize_code(str(h.get("code", "")))
        if code:
            out[code] = dict(h)
    for w in snapshot.get("watchlist") or []:
        code = _normalize_code(str(w.get("code", "")))
        if code:
            out[code] = {**out.get(code, {}), **dict(w)}
    code = snapshot.get("code")
    if code:
        c = _normalize_code(str(code))
        out[c] = {
            **out.get(c, {}),
            **{
                k: snapshot[k]
                for k in ("price", "name", "change_pct", "ma20", "sector", "industry", "volume", "turnover")
                if k in snapshot
            },
        }

    cfg = settings
    if cfg is None:
        try:
            from agent_reach.daily_run.settings import load_settings

            cfg = load_settings()
        except Exception:
            cfg = None
    if cfg:
        from agent_reach.daily_run.sector_classifier import enrich_symbol_map_sectors

        out = enrich_symbol_map_sectors(out, cfg)
    return out


def portfolio_from_snapshot(enriched: dict[str, Any]) -> dict[str, Any]:
    """Rebuild portfolio dict from enriched snapshot (avoids extra disk read)."""
    block = enriched.get("portfolio") or {}
    return {
        "total": block.get("total"),
        "cash": block.get("cash"),
        "cash_ratio": block.get("cash_ratio"),
        "holdings": [dict(h) for h in (block.get("holdings") or [])],
        "watchlist": [dict(w) for w in (enriched.get("watchlist") or [])],
    }


def sync_snapshot_portfolio(snapshot: dict[str, Any], portfolio: dict[str, Any]) -> None:
    """Apply portfolio.json fields onto snapshot blocks in-place."""
    snapshot["watchlist"] = list(portfolio.get("watchlist") or [])
    block = dict(snapshot.get("portfolio") or {})
    for key in ("holdings", "cash", "cash_ratio", "total"):
        if key in portfolio:
            block[key] = portfolio[key]
    snapshot["portfolio"] = block


def list_target_symbols(
    portfolio: dict[str, Any],
    *,
    mode: str = "all",
) -> list[str]:
    """Return ordered unique symbol codes from portfolio.

    mode:
      - all: holdings then watchlist (deduped)
      - holdings: holdings only
      - watchlist: watchlist only
    """
    codes: list[str] = []
    seen: set[str] = set()

    def _add(items: list[dict[str, Any]]) -> None:
        for row in items:
            code = _normalize_code(str(row.get("code", "")))
            if code and code not in seen:
                seen.add(code)
                codes.append(code)

    if mode in ("all", "holdings"):
        _add(list(portfolio.get("holdings") or []))
    if mode in ("all", "watchlist"):
        _add(list(portfolio.get("watchlist") or []))
    return codes


def resolve_target_symbols(
    portfolio: dict[str, Any],
    settings: dict[str, Any],
    *,
    workflow: str | None = None,
) -> list[str]:
    """Resolve which symbols to run for morning/close/intraday jobs.

    intraday_symbols_mode (when workflow=intraday):
      - all / holdings+watchlist: 持仓 + 观察池（去重）
      - holdings: 仅持仓
      - watchlist: 仅观察池
      - primary: 主标的
    close_symbols_mode (when workflow=close):
      - same values as intraday; defaults to schedule.symbols_mode when unset
    Falls back to schedule.symbols_mode when workflow-specific mode is unset.
    """
    sched = settings.get("schedule") or {}
    if workflow == "intraday":
        mode = str(
            sched.get("intraday_symbols_mode") or sched.get("symbols_mode", "primary")
        ).lower()
        # Shorthand: scan holdings + 观察池 (same as mode=all, excludes duplicate codes)
        if mode in ("holdings+watchlist", "holdings_watchlist"):
            mode = "all"
    elif workflow == "close":
        mode = str(
            sched.get("close_symbols_mode") or sched.get("symbols_mode", "primary")
        ).lower()
        if mode in ("holdings+watchlist", "holdings_watchlist"):
            mode = "all"
    else:
        mode = str(sched.get("symbols_mode", "primary")).lower()
    if mode == "primary":
        code = portfolio.get("primary_code")
        if not code and portfolio.get("holdings"):
            code = portfolio["holdings"][0]["code"]
        if code:
            return [_normalize_code(str(code))]
        return ["MARKET"]
    return list_target_symbols(portfolio, mode=mode)


def is_redundant_symbol_name(name: Any, code: str) -> bool:
    """True when *name* adds no information beyond the normalized code."""
    norm = _normalize_code(code)
    if not name or not str(name).strip():
        return True
    text = str(name).strip()
    if _normalize_code(text) == norm:
        return True
    compact = text.replace(" ", "")
    return compact in {norm, f"{norm}({norm})", f"{norm}（{norm}）"}


def _portfolio_rows(
    portfolio: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if portfolio:
        rows.extend(list(portfolio.get("holdings") or []))
        rows.extend(list(portfolio.get("watchlist") or []))
    if snapshot:
        block = snapshot.get("portfolio") or {}
        rows.extend(list(block.get("holdings") or []))
        rows.extend(list(snapshot.get("watchlist") or []))
    return rows


def resolve_symbol_name(
    portfolio: dict[str, Any] | None,
    code: str,
    *,
    fallback: Any = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Resolve a human-readable symbol name; never return code duplicated as name."""
    norm = _normalize_code(code)
    for row in _portfolio_rows(portfolio, snapshot=snapshot):
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        row_name = row.get("name")
        if row_name and not is_redundant_symbol_name(row_name, norm):
            return str(row_name).strip()
    if fallback is not None and not is_redundant_symbol_name(fallback, norm):
        return str(fallback).strip()
    return norm


def format_symbol_reference(
    name: Any,
    code: str,
    *,
    portfolio: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Display label like 水晶光电(002273); omit parens when only the code is known."""
    norm = _normalize_code(code)
    resolved = resolve_symbol_name(portfolio, norm, fallback=name, snapshot=snapshot)
    if is_redundant_symbol_name(resolved, norm):
        return norm
    return f"{resolved}({norm})"


def symbol_display_name(
    portfolio: dict[str, Any],
    code: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Best-effort name lookup from portfolio rows."""
    return resolve_symbol_name(portfolio, code, snapshot=snapshot)
