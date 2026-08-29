# -*- coding: utf-8
"""Morning Feishu card layout — holdings overview + global markets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.report_push import ReportSection
from agent_reach.daily_run.snapshot_builder import _normalize_code

MORNING_CARD_ORDER: tuple[str, ...] = (
    "holdings_overview",
    "experts",
    "decision",
    "xueqiu_hot",
    "eastmoney",
    "harness",
    "ai_narrative",
)

MORNING_CARD_LABELS: dict[str, str] = {
    "holdings_overview": "📋 持仓早盘速览",
    "experts": "👥 专家共识",
    "decision": "📊 MSS 决策",
    "xueqiu_hot": "🔥 雪球热门",
    "eastmoney": "📰 东财路由",
    "harness": "🧬 Harness 进化",
    "ai_narrative": "📋 规则解读",
}


def morning_card_layout_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = (settings or {}).get("report") or {}
    layout = str(cfg.get("morning_card_layout", "cards")).lower()
    return layout not in ("legacy", "old", "false", "0")


@dataclass
class MorningSymbolRow:
    code: str
    name: str
    holding: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class MorningCardContext:
    portfolio: dict[str, Any] = field(default_factory=dict)
    symbol_rows: list[MorningSymbolRow] = field(default_factory=list)
    global_markets: Optional[dict[str, Any]] = None
    team_markdown: str = ""
    harness_markdown: str = ""
    narrative: Optional[dict[str, Any]] = None
    macro_signals: Optional[dict[str, Any]] = None
    primary_snapshot: Optional[dict[str, Any]] = None
    settings: Optional[dict[str, Any]] = None


def _portfolio_total(portfolio: dict[str, Any]) -> float:
    total = portfolio.get("total")
    if total is not None:
        try:
            val = float(total)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    cash = float(portfolio.get("cash") or 0)
    holdings_mv = 0.0
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        shares = int(row.get("shares") or 0)
        price = row.get("price") or row.get("cost") or 0
        try:
            holdings_mv += shares * float(price)
        except (TypeError, ValueError):
            continue
    return cash + holdings_mv if (cash + holdings_mv) > 0 else 0.0


def _holding_weight_pct(holding: dict[str, Any], portfolio: dict[str, Any]) -> Optional[float]:
    total = _portfolio_total(portfolio)
    if total <= 0:
        return None
    shares = int(holding.get("shares") or 0)
    price = holding.get("price") or holding.get("cost")
    if shares <= 0 or price is None:
        return 0.0
    try:
        return round(shares * float(price) / total * 100.0, 1)
    except (TypeError, ValueError):
        return None


def _parse_target_pct_from_action(action: str, *, current_pct: float) -> Optional[float]:
    text = str(action or "").strip()
    if not text:
        return None
    if any(k in text for k in ("禁止", "回避", "清仓", "卖出")):
        return 0.0
    if "不加仓" in text or "观望" in text or "持有" in text:
        return current_pct
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    if "小仓" in text:
        return min(current_pct, 10.0) if current_pct > 0 else 10.0
    return None


def _target_position_pct(
    report: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    current_pct: float,
    settings: Optional[dict[str, Any]],
) -> tuple[float, str]:
    from agent_reach.daily_run.berkshire.decision_memo import build_decision_memo
    from agent_reach.daily_run.settings import effective_settings

    cfg = effective_settings(settings or {})
    position_cfg = cfg.get("position") or {}
    max_position = float(position_cfg.get("max_position_pct", 35.0))

    memo = build_decision_memo(snapshot, settings=cfg)
    tiers = list(memo.get("tiers") or [])
    target: Optional[float] = None
    source_action = ""
    for tier in tiers:
        if str(tier.get("strategy") or "") == "稳健型":
            source_action = str(tier.get("action") or "")
            target = _parse_target_pct_from_action(source_action, current_pct=current_pct)
            break
    if target is None and tiers:
        source_action = str(tiers[0].get("action") or "")
        target = _parse_target_pct_from_action(source_action, current_pct=current_pct)
    if target is None:
        verdict = str(report.get("verdict") or "")
        if verdict == "回避":
            target = 0.0
            source_action = "标签回避"
        elif verdict == "可做":
            target = min(max_position, max(current_pct, 20.0))
            source_action = "MSS 可做"
        else:
            target = current_pct
            source_action = "观察持有"
    target = max(0.0, min(float(max_position), float(target)))
    return round(target, 1), source_action


def _position_advice_line(
    holding: dict[str, Any],
    portfolio: dict[str, Any],
    report: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]],
) -> str:
    current = _holding_weight_pct(holding, portfolio)
    if current is None:
        return "—"
    target, _source = _target_position_pct(
        report,
        snapshot,
        current_pct=current,
        settings=settings,
    )
    if target < current - 0.4:
        action = "减仓"
    elif target > current + 0.4:
        action = "加仓"
    else:
        action = "持有"
    return f"{action} · 当前 {current:.1f}% → 目标 {target:.1f}%"


def _reference_price(holding: dict[str, Any], snapshot: dict[str, Any]) -> Optional[float]:
    for key in ("prev_close", "reference_price", "last_close"):
        raw = holding.get(key) if key in holding else snapshot.get(key)
        if raw is not None:
            try:
                val = float(raw)
                if val > 0:
                    return round(val, 2)
            except (TypeError, ValueError):
                continue
    price = holding.get("price") or snapshot.get("price")
    change = holding.get("change_pct") if holding.get("change_pct") is not None else snapshot.get("change_pct")
    if price is not None and change is not None:
        try:
            px = float(price)
            pct = float(change)
            if abs(pct) <= 1.5 and pct != 0:
                pct *= 100.0
            if pct != -100.0:
                return round(px / (1.0 + pct / 100.0), 2)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return None


def _change_vs_prev_close(
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    suspended: bool,
) -> str:
    if suspended:
        return "—"
    prev = _reference_price(holding, snapshot)
    price = holding.get("price") or snapshot.get("price")
    if prev is None or price is None:
        raw = holding.get("change_pct") if holding.get("change_pct") is not None else snapshot.get("change_pct")
        if raw is None:
            return "—"
        pct = float(raw)
        if abs(pct) <= 1.5 and pct != 0:
            pct *= 100.0
        base = "（昨收基准）" if prev is None else f"（昨收 ¥{prev:.2f}）"
        return f"{pct:+.2f}% {base}"
    try:
        px = float(price)
        pct = (px - float(prev)) / float(prev) * 100.0
        return f"{pct:+.2f}%（昨收 ¥{float(prev):.2f}）"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def _format_open_cell(holding: dict[str, Any], snapshot: dict[str, Any], *, suspended: bool) -> str:
    from agent_reach.daily_run.tradability import is_suspended

    if suspended or is_suspended(holding) or is_suspended(snapshot):
        return "🔒 停牌"
    open_px = holding.get("open") or snapshot.get("open")
    if open_px is None:
        return "待开盘"
    try:
        val = float(open_px)
    except (TypeError, ValueError):
        return "待开盘"
    if val <= 0:
        return "待开盘"
    return f"¥{val:.2f}"


def _format_price_cell(holding: dict[str, Any], snapshot: dict[str, Any], *, suspended: bool) -> str:
    if suspended:
        return "🔒 停牌"
    price = holding.get("price") or snapshot.get("price")
    if price is None:
        return "—"
    try:
        val = float(price)
    except (TypeError, ValueError):
        return "—"
    if val <= 0:
        return "待开盘"
    return f"¥{val:.2f}"


def _trigger_lines(
    report: dict[str, Any],
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    suspended: bool,
) -> str:
    if suspended:
        return "—"
    price_raw = holding.get("price") or snapshot.get("price")
    if price_raw is None:
        return "—"
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return "—"
    if price <= 0:
        return "—"

    lines: list[str] = []
    stop = report.get("stop_loss_price")
    if stop is not None:
        stop_f = round(float(stop), 2)
        if price <= stop_f:
            lines.append(f"止损 {stop_f:.2f} ✅已触发 → 减仓/清仓")
        else:
            lines.append(f"止损 {stop_f:.2f}")
    entry = report.get("entry_price")
    if entry is not None:
        entry_f = round(float(entry), 2)
        if price >= entry_f:
            lines.append(f"入场 {entry_f:.2f} ✅已触发 → 按 MSS 纪律")
        else:
            lines.append(f"入场 {entry_f:.2f}")
    ma20 = holding.get("ma20") or snapshot.get("ma20")
    if ma20 is not None:
        ma20_f = round(float(ma20), 2)
        if price < ma20_f:
            lines.append(f"MA20 {ma20_f:.2f} ✅已触发 → 关注失效条件")
        else:
            lines.append(f"MA20 {ma20_f:.2f}")
    return " · ".join(lines[:3]) if lines else "—"


def build_merged_morning_card_context(
    *,
    symbol_results: list[dict[str, Any]],
    decision_entries: list[tuple],
    primary_snapshot: dict[str, Any],
    team_markdown: str = "",
    harness_markdown: str = "",
    narrative: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    global_markets: Optional[dict[str, Any]] = None,
) -> MorningCardContext:
    from agent_reach.daily_run.global_markets_collector import fetch_key_global_markets

    portfolio = dict((primary_snapshot.get("portfolio") or {}))
    holdings = {
        _normalize_code(str(h.get("code") or "")): dict(h)
        for h in (portfolio.get("holdings") or [])
        if isinstance(h, dict)
    }
    report_by_code: dict[str, dict[str, Any]] = {}
    snapshot_by_code: dict[str, dict[str, Any]] = {}
    for entry in decision_entries:
        name, code, report = entry[0], entry[1], entry[2]
        snap = entry[3] if len(entry) > 3 else {}
        norm = _normalize_code(str(code or ""))
        report_by_code[norm] = dict(report or {})
        snapshot_by_code[norm] = dict(snap or {})
        if norm in holdings:
            holdings[norm]["name"] = holdings[norm].get("name") or name

    rows: list[MorningSymbolRow] = []
    seen: set[str] = set()
    for entry in decision_entries:
        code = _normalize_code(str(entry[1] or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        holding = holdings.get(code) or {"code": code, "name": entry[0], "shares": 0}
        rows.append(
            MorningSymbolRow(
                code=code,
                name=str(entry[0] or holding.get("name") or code),
                holding=holding,
                report=report_by_code.get(code) or {},
                snapshot=snapshot_by_code.get(code) or {},
            )
        )
    for code, holding in holdings.items():
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            MorningSymbolRow(
                code=code,
                name=str(holding.get("name") or code),
                holding=holding,
                report=report_by_code.get(code) or {},
                snapshot=snapshot_by_code.get(code) or {},
            )
        )

    markets = global_markets if global_markets is not None else fetch_key_global_markets()
    return MorningCardContext(
        portfolio=portfolio,
        symbol_rows=rows,
        global_markets=markets,
        team_markdown=team_markdown,
        harness_markdown=harness_markdown,
        narrative=narrative,
        macro_signals=primary_snapshot.get("macro_signals"),
        primary_snapshot=primary_snapshot,
        settings=settings,
    )


def build_single_morning_card_context(
    run_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    global_markets: Optional[dict[str, Any]] = None,
) -> MorningCardContext:
    from agent_reach.daily_run.global_markets_collector import fetch_key_global_markets

    snap = run_result.get("snapshot") or {}
    report = (run_result.get("evaluation") or {}).get("report") or {}
    code = _normalize_code(str(snap.get("code") or report.get("code") or ""))
    pf = dict(snap.get("portfolio") or {})
    holding = {}
    for row in pf.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) == code:
            holding = dict(row)
            break
    markets = global_markets if global_markets is not None else fetch_key_global_markets()
    return MorningCardContext(
        portfolio=pf,
        symbol_rows=[
            MorningSymbolRow(
                code=code,
                name=str(snap.get("name") or report.get("name") or code),
                holding=holding,
                report=report,
                snapshot=snap,
            )
        ],
        global_markets=markets,
        team_markdown=run_result.get("team_markdown") or "",
        harness_markdown=run_result.get("harness_markdown") or "",
        narrative=run_result.get("llm_narrative"),
        macro_signals=snap.get("macro_signals"),
        primary_snapshot=snap,
        settings=settings,
    )


def render_holdings_overview_markdown(ctx: MorningCardContext) -> str:
    from agent_reach.daily_run.global_markets_collector import render_global_markets_markdown
    from agent_reach.daily_run.morning_content_scope import (
        render_domestic_market_brief,
        render_macro_headlines_markdown,
        render_prior_close_recap_markdown,
        select_macro_headlines,
    )
    from agent_reach.daily_run.tradability import is_suspended

    lines: list[str] = []
    snap = ctx.primary_snapshot or {}

    recap_md = render_prior_close_recap_markdown(ctx.portfolio, settings=ctx.settings)
    if recap_md.strip():
        lines.append(recap_md)
        lines.append("")

    global_md = render_global_markets_markdown(ctx.global_markets)
    if global_md.strip():
        lines.append(global_md)
        lines.append("")

    market_md = render_domestic_market_brief(snapshot=snap, macro_signals=ctx.macro_signals)
    if market_md.strip():
        lines.append(market_md)
        lines.append("")

    featured, extra = select_macro_headlines(
        macro_signals=ctx.macro_signals,
        sources=snap.get("sources"),
        portfolio=ctx.portfolio,
        limit=3,
    )
    macro_md = render_macro_headlines_markdown(featured, extra)
    if macro_md.strip():
        lines.append(macro_md)
        lines.append("")

    lines.extend(
        [
            "**持仓早盘速览**",
            "",
            "| 标的 | 开盘 | 现价 | 较昨收 | MSS | 结论 | 触发位 | 仓位建议 |",
            "|------|------|------|--------|-----|------|--------|----------|",
        ]
    )
    for row in ctx.symbol_rows:
        holding = row.holding
        snap = row.snapshot
        report = row.report
        merged = {**snap, **holding}
        suspended = is_suspended(merged)
        mss = report.get("mss_final")
        mss_s = f"{float(mss):.1f}" if mss is not None else "—"
        lines.append(
            f"| {row.name} | {_format_open_cell(holding, snap, suspended=suspended)} "
            f"| {_format_price_cell(holding, snap, suspended=suspended)} "
            f"| {_change_vs_prev_close(holding, snap, suspended=suspended)} "
            f"| {mss_s} | {report.get('verdict') or '—'} "
            f"| {_trigger_lines(report, holding, snap, suspended=suspended)} "
            f"| {_position_advice_line(holding, ctx.portfolio, report, snap, settings=ctx.settings)} |"
        )
    return "\n".join(lines).strip()


def render_decision_markdown(ctx: MorningCardContext) -> str:
    from agent_reach.daily_run.morning_content_scope import (
        render_merged_symbol_logic_markdown,
        render_symbol_morning_logic_markdown,
    )

    entries = [
        (row.name, row.code, row.report, row.snapshot)
        for row in ctx.symbol_rows
        if row.report
    ]
    if not entries:
        return ""
    if len(entries) == 1:
        row = ctx.symbol_rows[0]
        return render_symbol_morning_logic_markdown(row.report, snapshot=row.snapshot)
    return render_merged_symbol_logic_markdown(entries)


def render_experts_markdown(ctx: MorningCardContext) -> str:
    return (ctx.team_markdown or "").strip()


def render_xueqiu_hot_markdown(ctx: MorningCardContext) -> str:
    return ""


def render_eastmoney_markdown(ctx: MorningCardContext) -> str:
    return ""


def render_harness_markdown(ctx: MorningCardContext) -> str:
    return (ctx.harness_markdown or "").strip()


def render_ai_narrative_markdown(ctx: MorningCardContext) -> str:
    from agent_reach.daily_run.morning_content_scope import render_scoped_morning_narrative_markdown

    return render_scoped_morning_narrative_markdown(ctx.narrative)


_CARD_RENDERERS = {
    "holdings_overview": render_holdings_overview_markdown,
    "experts": render_experts_markdown,
    "decision": render_decision_markdown,
    "xueqiu_hot": render_xueqiu_hot_markdown,
    "eastmoney": render_eastmoney_markdown,
    "harness": render_harness_markdown,
    "ai_narrative": render_ai_narrative_markdown,
}


def render_morning_card_sections(ctx: MorningCardContext) -> list[ReportSection]:
    sections: list[ReportSection] = []
    for category in MORNING_CARD_ORDER:
        renderer = _CARD_RENDERERS[category]
        body = renderer(ctx)
        if not (body or "").strip():
            continue
        sections.append(ReportSection(category=category, title="", body=body.strip()))
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        label = MORNING_CARD_LABELS.get(sec.category, sec.category)
        sec.title = f"{label} {i}/{total}"
    return sections
