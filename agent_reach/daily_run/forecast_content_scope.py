# -*- coding: utf-8
"""Sunday forecast content scope — de-dupe, compress, holdings-only focus."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_MACRO_MAX_CHARS = 100
_HOLDINGS_BUDGET_CHARS = 300
_WEEKLY_REPORT_LINK = "详见本周周报（周六推送）"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truncate(text: str, limit: int) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def holding_sector_names(
    portfolio: Optional[dict[str, Any]] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> set[str]:
    cfg = (settings or {}).get("watchlist") or {}
    sector_map = cfg.get("sector_map") or {}
    names: set[str] = set()
    for h in (portfolio or {}).get("holdings") or []:
        code = _normalize_code(str(h.get("code") or ""))
        sector = sector_map.get(code) or h.get("sector") or h.get("industry")
        if sector:
            names.add(str(sector))
    return names


def filter_sectors_to_holdings(
    sectors: list[dict[str, Any]],
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    allowed = holding_sector_names(portfolio, settings=settings)
    if not allowed:
        return sectors[:2]
    out = [s for s in sectors if str(s.get("name") or "") in allowed]
    return out[:3]


def build_weekly_recap_one_liner(
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    as_of: Optional[date] = None,
) -> str:
    """One-sentence prior-week performance; details deferred to weekly report."""
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.weekly_card_metrics import build_weekly_return_metrics
    from agent_reach.daily_run.weekly_report import trading_week_range
    from agent_reach.daily_run.weekly_signals import build_holdings_contribution_table

    d = as_of or today_shanghai()
    week_start, week_end = trading_week_range(d - timedelta(days=7))
    pf = portfolio or {}
    start_total = _optional_float(pf.get("total_value") or pf.get("total"))
    end_total = start_total
    try:
        metrics = build_weekly_return_metrics(
            week_start=week_start,
            week_end=week_end,
            start_total=start_total,
            end_total=end_total,
            weekly_pnl=None,
            weekly_pnl_pct=None,
            settings=settings,
        )
        week_pct = _optional_float(metrics.get("absolute_return_pct"))
        excess = _optional_float(metrics.get("excess_return_pct"))
    except Exception:
        week_pct = None
        excess = None

    holdings = list(pf.get("holdings") or [])
    contrib_rows = build_holdings_contribution_table(holdings)
    top = contrib_rows[0] if contrib_rows else {}
    top_name = str(top.get("name") or "")

    parts: list[str] = []
    if week_pct is not None:
        parts.append(f"本周组合 {_fmt_pct(week_pct)}")
    if excess is not None:
        parts.append(f"跑赢基准 {excess:+.1f}%")
    if top_name and float(top.get("contribution_pct") or 0) > 0:
        parts.append(f"{top_name}贡献最大")
    if not parts:
        return f"本周表现 {_WEEKLY_REPORT_LINK}"
    return _truncate("，".join(parts) + f"。{_WEEKLY_REPORT_LINK}", 120)


def _infer_macro_theme(macro: str, mss: Optional[float]) -> str:
    text = macro or ""
    if any(k in text for k in ("鹰", "加息", "紧缩", "回落")):
        return "美联储偏鹰/流动性收紧"
    if any(k in text for k in ("北向", "净流入", "放量")):
        return "北向/资金面改善"
    if any(k in text for k in ("存储", "半导体", "AI", "芯片")):
        return "科技链景气预期"
    if mss is not None and mss >= 55:
        return f"MSS {mss:.0f} 分偏多"
    if mss is not None and mss < 45:
        return f"MSS {mss:.0f} 分偏空"
    return _truncate(text, 36) if text else "宏观中性"


def _macro_impact_on_holdings(
    theme: str,
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    mss: Optional[float] = None,
) -> str:
    sectors = holding_sector_names(portfolio, settings=settings)
    tech_like = bool(sectors & {"半导体", "存储", "光通信", "AI算力", "面板"})
    if "鹰" in theme or "收紧" in theme or "偏空" in theme:
        if tech_like:
            return "利空成长股，建议降低科技仓位至50%以下"
        return "偏防御，建议总仓位≤60%"
    if "资金面" in theme or "偏多" in theme:
        if tech_like:
            return "利好持仓科技链，维持龙头权重"
        return "偏多环境，维持现有仓位结构"
    if mss is not None and mss >= 55:
        return "偏多，持仓以持有为主"
    if mss is not None and mss < 45:
        return "偏空，优先控仓与止损"
    return "对持仓影响有限，按个股预案执行"


def build_macro_brief_with_impact(
    *,
    snapshot: Optional[dict[str, Any]] = None,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    snap = snapshot or {}
    macro = str(snap.get("macro_summary") or "").strip()
    mss = _optional_float(snap.get("mss_final"))
    if not macro and not mss:
        return {"text": "", "related_to_holdings": False}
    theme = _infer_macro_theme(macro, mss)
    impact = _macro_impact_on_holdings(theme, portfolio=portfolio, settings=settings, mss=mss)
    line = _truncate(f"{theme} → {impact}", _MACRO_MAX_CHARS)
    extra_links = []
    for r in (snap.get("news_research") or [])[:1]:
        label = r.get("label") or "宏观延伸阅读"
        if r.get("summary"):
            extra_links.append(str(label))
    return {
        "text": line,
        "theme": theme,
        "impact": impact,
        "related_to_holdings": True,
        "extra_reading": extra_links,
    }


def build_market_reference_one_liner(
    macro_signals: Optional[dict[str, Any]] = None,
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """Single-line non-holding market color (optional)."""
    signals = macro_signals or {}
    hot = list(signals.get("hot_stocks") or [])[:1]
    if not hot:
        return ""
    name = str(hot[0].get("name") or hot[0].get("symbol") or "")
    if not name:
        return ""
    held = {
        _normalize_code(str(h.get("code") or ""))
        for h in (portfolio or {}).get("holdings") or []
    }
    hot_code = _normalize_code(str(hot[0].get("code") or hot[0].get("symbol") or ""))
    if hot_code and hot_code in held:
        return ""
    return _truncate(f"市场参考：热点 {name}（非持仓，不纳入下周操作）", 60)


def _symbol_announcement_risk(
    code: str,
    watchlist_intel: Optional[dict[str, Any]] = None,
    risk_calendar: Optional[list[dict[str, Any]]] = None,
) -> Optional[str]:
    block = (watchlist_intel or {}).get(code) or {}
    for ann in (block.get("announcements") or [])[:1]:
        title = str(ann.get("title") or "")[:20]
        pub = str(ann.get("date") or ann.get("pub_date") or "")[:10]
        if title:
            return f"公告披露{pub[5:] if len(pub) >= 10 else pub} {title}"
    for row in risk_calendar or []:
        if code and code in str(row.get("event") or ""):
            return _truncate(str(row.get("event") or ""), 28)
    return None


def build_symbol_core_factors(
    sym: dict[str, Any],
    *,
    enriched: Optional[dict[str, Any]] = None,
    watchlist_intel: Optional[dict[str, Any]] = None,
    risk_calendar: Optional[list[dict[str, Any]]] = None,
    kronos: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Stock-specific factors only — skip generic boilerplate when possible."""
    code = str(sym.get("code") or "")
    row = enriched or {}
    factors: list[str] = []
    price = _optional_float(row.get("price") or sym.get("price_mid") or sym.get("base_price"))
    ma20 = _optional_float(row.get("ma20"))
    hi = _optional_float(sym.get("price_high"))
    if price and ma20 and hi and abs(hi - price) / price <= 0.08:
        factors.append(f"②技术面接近前高{hi:.0f}元压力位")
    elif price and ma20:
        rel = "站稳" if price >= ma20 else "跌破"
        factors.append(f"②技术面{rel}20日均线")
    chg = _optional_float(row.get("change_pct"))
    if chg is not None and abs(chg) >= 3:
        factors.append(f"①周内波动{chg:+.1f}%")
    ann = _symbol_announcement_risk(code, watchlist_intel, risk_calendar)
    if ann:
        factors.append(f"③{ann}（不确定性）")
    if kronos and kronos.get("available"):
        cum = _optional_float(kronos.get("cum_change_pct"))
        if cum is not None and abs(cum) >= 3:
            factors.append(f"③Kronos路径{cum:+.1f}%")
    sector = row.get("sector") or row.get("industry")
    if sector and len(factors) < 2:
        factors.append(f"①{sector}链持仓")
    return factors[:3]


def format_compact_symbol_line(
    sym: dict[str, Any],
    *,
    core_factors: Optional[list[str]] = None,
) -> str:
    name = str(sym.get("name") or sym.get("code") or "—")
    lo = sym.get("price_low")
    hi = sym.get("price_high")
    conf = sym.get("confidence_pct")
    if lo is None or hi is None:
        return _truncate(str(sym.get("text") or name), 80)
    factors = [f for f in (core_factors or []) if f]
    base = f"{name}下周预测 {lo:.0f}-{hi:.0f}元"
    if conf is not None:
        base += f"，置信度{float(conf):.0f}%"
    if factors:
        numbered = []
        for i, f in enumerate(factors[:3], start=1):
            f = re.sub(r"^[①②③]", "", f).strip()
            numbered.append(f"{i}{f}" if not f[0].isdigit() else f)
        return f"{base}，核心因素：{'；'.join(numbered)}"
    return f"{base}，暂无额外特异因素"


def apply_holdings_char_budget(lines: list[str], *, budget: int = _HOLDINGS_BUDGET_CHARS) -> list[str]:
    if not lines:
        return lines
    total = sum(len(s) for s in lines)
    if total <= budget:
        return lines
    # Drop core factors from tail items first
    trimmed: list[str] = []
    for line in lines:
        if "核心因素" in line and total > budget:
            short = line.split("，核心因素：")[0]
            total -= len(line) - len(short)
            trimmed.append(short)
        else:
            trimmed.append(_truncate(line, max(48, budget // max(len(lines), 1))))
    if sum(len(s) for s in trimmed) > budget:
        return [_truncate(s, budget // len(trimmed)) for s in trimmed]
    return trimmed


def extract_buy_candidates(
    outlook: Optional[dict[str, Any]] = None,
    *,
    held_codes: Optional[set[str]] = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    held = held_codes or set()
    rows: list[dict[str, Any]] = []
    for item in (outlook or {}).get("operation_plan") or []:
        action = str(item.get("action") or "")
        if action not in ("买入", "新建仓"):
            continue
        code = _normalize_code(str(item.get("code") or ""))
        if code and code in held:
            continue
        trigger = str(item.get("trigger") or "触发条件见收盘 handoff")
        target = str(item.get("target_weight") or "—")
        stop = str(item.get("stop_loss") or "—")
        rows.append(
            {
                "code": code,
                "name": item.get("name") or code,
                "action": action,
                "label": "新建仓候选",
                "text": (
                    f"【新建仓候选】{item.get('name')}：{trigger}；"
                    f"目标仓位 {target}；止损 {stop}"
                ),
            }
        )
    return rows[:limit]


def build_forecast_content_scope(
    *,
    structured: dict[str, Any],
    forecast: dict[str, Any],
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    digest: Optional[dict[str, Any]] = None,
    outlook: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
    enriched: Optional[dict[str, Any]] = None,
    watchlist_intel: Optional[dict[str, Any]] = None,
    risk_calendar: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    snap = snapshot or forecast.get("_snapshot") or {}
    pf = portfolio or {}
    held_codes = {
        _normalize_code(str(h.get("code") or ""))
        for h in pf.get("holdings") or []
        if h.get("code")
    }
    sectors = filter_sectors_to_holdings(
        list(structured.get("sectors") or []),
        portfolio=pf,
        settings=settings,
    )
    symbols = list(structured.get("symbols") or [])
    enriched_map = enriched or {}
    intel = watchlist_intel or forecast.get("watchlist_intel") or {}
    risks = risk_calendar or []
    kronos_paths = forecast.get("kronos_paths") or {}

    compact_lines: list[str] = []
    for sym in symbols:
        code = _normalize_code(str(sym.get("code") or ""))
        factors = build_symbol_core_factors(
            sym,
            enriched=enriched_map.get(code),
            watchlist_intel=intel,
            risk_calendar=risks,
            kronos=kronos_paths.get(code),
        )
        compact_lines.append(format_compact_symbol_line(sym, core_factors=factors))
    compact_lines = apply_holdings_char_budget(compact_lines)

    buy_candidates = extract_buy_candidates(outlook, held_codes=held_codes)
    week_start = forecast.get("week_start")
    as_of = date.fromisoformat(str(week_start)) if week_start else None

    extra_reading: list[str] = []
    for r in (forecast.get("news_research") or [])[:2]:
        if r.get("label"):
            extra_reading.append(str(r["label"]))
    for r in ((digest or {}).get("sector_research") or [])[:1]:
        if r.get("label"):
            extra_reading.append(str(r["label"]))

    return {
        "weekly_recap": build_weekly_recap_one_liner(
            portfolio=pf, settings=settings, as_of=as_of
        ),
        "macro_brief": build_macro_brief_with_impact(
            snapshot=snap, portfolio=pf, settings=settings
        ),
        "market_reference": build_market_reference_one_liner(
            forecast.get("macro_signals"), portfolio=pf, settings=settings
        ),
        "sectors_scoped": sectors,
        "symbols_compact": compact_lines,
        "buy_candidates": buy_candidates,
        "extra_reading": extra_reading[:3],
        "weekly_report_link": _WEEKLY_REPORT_LINK,
    }


def _fmt_pct(value: float) -> str:
    return f"{value:+.1f}%"
