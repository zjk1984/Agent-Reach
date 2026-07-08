# -*- coding: utf-8
"""Build daily-run snapshots from portfolio config + live quotes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.macro_collector import collect_macro_context
from agent_reach.daily_run.mss_forecast import forecast_mss_range


def default_portfolio_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "portfolio.json"


def example_portfolio_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "daily_run_portfolio.example.json"


def load_portfolio(path: Optional[Path] = None) -> dict[str, Any]:
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


def _normalize_code(code: str) -> str:
    return code.zfill(6)[-6:] if str(code).isdigit() else str(code)


def fetch_quotes_map(codes: list[str], config=None) -> dict[str, dict[str, Any]]:
    """Batch fetch quotes for multiple codes (parallel xueqiu + AKShare batch fallback)."""
    unique = list(dict.fromkeys(_normalize_code(c) for c in codes if c))
    result: dict[str, dict[str, Any]] = {}
    if not unique:
        return result

    def _fetch_xueqiu(code: str) -> Optional[tuple[str, dict[str, Any]]]:
        try:
            from agent_reach.channels import xueqiu as xq_mod

            xq_mod._ensure_cookies()
            channel = xq_mod.XueqiuChannel()
            q = channel.get_stock_quote(code_to_xueqiu_symbol(code))
            price = q.get("current")
            if price is None:
                return None
            return code, {
                "code": code,
                "name": q.get("name", code),
                "price": float(price),
                "change_pct": float(q.get("percent") or 0),
                "reference_price": float(q.get("last_close") or price),
                "source": "xueqiu",
            }
        except Exception:
            return None

    workers = min(8, max(1, len(unique)))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for item in pool.map(_fetch_xueqiu, unique):
                if item:
                    code, quote = item
                    result[code] = quote
    except Exception:
        pass

    missing = [c for c in unique if c not in result]
    if missing:
        try:
            from agent_reach.daily_run.akshare_adapter import fetch_quotes_batch

            batch = fetch_quotes_batch(missing)
            for code in missing:
                if code in batch:
                    result[code] = batch[code]
        except Exception:
            pass

    return result


def _attach_technicals(quote: dict[str, Any], code: str) -> dict[str, Any]:
    out = dict(quote)
    try:
        from agent_reach.daily_run.akshare_adapter import fetch_technicals

        out.update(fetch_technicals(code))
    except Exception:
        pass
    return out


def enrich_holding(
    holding: dict[str, Any],
    quote_map: dict[str, dict[str, Any]],
    *,
    with_technicals: bool = False,
) -> dict[str, Any]:
    code = _normalize_code(str(holding.get("code", "")))
    out = dict(holding)
    quote = quote_map.get(code)
    if quote:
        out["price"] = quote["price"]
        out["change_pct"] = quote.get("change_pct")
        out["name"] = quote.get("name") or out.get("name")
        out["quote_source"] = quote.get("source")
        if with_technicals:
            enriched = _attach_technicals(quote, code)
            for k in ("ma20", "ma5", "position_20d", "volume_ratio"):
                if enriched.get(k) is not None:
                    out[k] = enriched[k]
    elif out.get("cost") is not None:
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
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a daily-run snapshot from portfolio + live macro/quotes."""
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    pf = portfolio or load_portfolio()
    code = primary_code or pf.get("primary_code") or "MARKET"
    if code == "MARKET" and pf.get("holdings"):
        code = str(pf["holdings"][0]["code"])

    code_norm = _normalize_code(str(code))
    holdings = [dict(h) for h in (pf.get("holdings") or [])]
    watchlist = [dict(w) for w in (pf.get("watchlist") or [])]

    macro_ctx = collect_macro_context(pf, config=config, settings=cfg) if enrich else {}

    primary_name = code_norm
    primary_price = None
    primary_ma20 = None
    primary_ma5 = None
    primary_pos = None
    primary_vol = None
    quote_summary_parts: list[str] = []
    has_cost_fallback = False

    if enrich:
        all_codes = [code_norm] + [
            _normalize_code(str(h.get("code", ""))) for h in holdings
        ] + [_normalize_code(str(w.get("code", ""))) for w in watchlist]
        quote_map = fetch_quotes_map(all_codes, config)

        if code_norm in quote_map:
            primary_quote = _attach_technicals(quote_map[code_norm], code_norm)
            quote_map[code_norm] = primary_quote
            primary_name = primary_quote.get("name", code_norm)
            primary_price = primary_quote.get("price")
            primary_ma20 = primary_quote.get("ma20")
            primary_ma5 = primary_quote.get("ma5")
            primary_pos = primary_quote.get("position_20d")
            primary_vol = primary_quote.get("volume_ratio")

        holdings = [
            enrich_holding(h, quote_map, with_technicals=_normalize_code(str(h.get("code", ""))) == code_norm)
            for h in holdings
        ]
        watchlist = [enrich_holding(w, quote_map) for w in watchlist]

        for eh in holdings + watchlist:
            if eh.get("quote_source") == "cost_fallback":
                has_cost_fallback = True
            if eh.get("price") is not None:
                chg = eh.get("change_pct")
                chg_s = f" {chg:+.2f}%" if chg is not None else ""
                quote_summary_parts.append(f"{eh.get('name')} {eh['price']}{chg_s}")

    portfolio_block = {
        "total": pf.get("total"),
        "cash_ratio": pf.get("cash_ratio"),
        "cash": pf.get("cash"),
        "holdings": holdings,
    }

    sources = dict(macro_ctx.get("sources") or {})
    if quote_summary_parts:
        sources["quote"] = {
            "summary": " · ".join(quote_summary_parts[:4]),
            "backend": "snapshot_builder",
        }

    mss_breakdown = dict(macro_ctx.get("mss_breakdown") or pf.get("mss_breakdown") or {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snapshot: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "report_type": report_type,
        "code": code_norm,
        "name": primary_name if report_type != "premarket" else f"{today} 早盘",
        "mss_breakdown": mss_breakdown,
        "sources": sources,
        "structured_review_complete": primary_ma20 is not None,
        "macro_summary": macro_ctx.get("macro_summary") or pf.get("macro_summary"),
        "macro_signals": macro_ctx.get("macro_signals"),
        "portfolio": portfolio_block,
        "watchlist": watchlist,
        "has_cost_fallback": has_cost_fallback,
    }

    if primary_price is not None:
        snapshot["price"] = primary_price
        snapshot["reference_price"] = primary_price
    if primary_ma20 is not None:
        snapshot["ma20"] = primary_ma20
    if primary_ma5 is not None:
        snapshot["ma5"] = primary_ma5
    if primary_pos is not None:
        snapshot["position_20d"] = primary_pos
    if primary_vol is not None:
        snapshot["volume_ratio"] = primary_vol

    if report_type == "premarket" and enrich:
        mss_range, forecast_meta = forecast_mss_range(snapshot, cfg)
        snapshot["mss_range"] = mss_range
        snapshot["mss_forecast"] = forecast_meta
    else:
        snapshot["mss_range"] = pf.get("mss_range")

    return snapshot


def build_and_save(
    output: Optional[Path] = None,
    *,
    report_type: str = "intraday",
    config=None,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], Path]:
    snap = build_snapshot(
        portfolio=portfolio,
        report_type=report_type,
        config=config,
        settings=settings,
    )
    out = output or (Path.home() / ".agent-reach" / "daily_run" / "last_snapshot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snap, out
