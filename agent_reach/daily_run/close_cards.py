# -*- coding: utf-8
"""Six-card Feishu layout for merged close review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.report_push import ReportSection
from agent_reach.daily_run.snapshot_builder import _normalize_code

CLOSE_CARD_ORDER: tuple[str, ...] = (
    "close_summary",
    "holdings_detail",
    "forecast_verify",
    "key_signals",
    "hot_research",
    "tomorrow_focus",
)

CLOSE_CARD_LABELS: dict[str, str] = {
    "close_summary": "📊 收盘摘要",
    "holdings_detail": "📈 持仓详情",
    "forecast_verify": "🔮 预测验证",
    "key_signals": "⚠️ 关键信号",
    "hot_research": "🔥 热点与调研",
    "tomorrow_focus": "📋 明日关注",
}


def close_card_layout_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = (settings or {}).get("report") or {}
    layout = str(cfg.get("close_card_layout", "six")).lower()
    return layout not in ("legacy", "old", "false", "0")


@dataclass
class CloseCardContext:
    portfolio_summary: dict[str, Any]
    symbol_rows: list[dict[str, Any]] = field(default_factory=list)
    verify_by_code: dict[str, dict[str, Any]] = field(default_factory=dict)
    forecast_review: Optional[dict[str, Any]] = None
    market_review: Optional[dict[str, Any]] = None
    macro_signals: Optional[dict[str, Any]] = None
    technical_scenarios: list[dict[str, Any]] = field(default_factory=list)
    research_results: list[dict[str, Any]] = field(default_factory=list)
    improvements: Optional[dict[str, Any]] = None
    narrative: Optional[dict[str, Any]] = None
    primary_snapshot: Optional[dict[str, Any]] = None
    settings: Optional[dict[str, Any]] = None


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(pct) <= 1.5 and abs(pct) != 0:
        pct *= 100.0
    return f"{pct:+.2f}%"


def _benchmark_vs_portfolio(
    portfolio_summary: dict[str, Any],
    market_review: Optional[dict[str, Any]],
    macro_signals: Optional[dict[str, Any]],
) -> str:
    port_pct = portfolio_summary.get("daily_pnl_pct")
    idx_pct: Optional[float] = None
    idx_name = "大盘"
    indices = (market_review or {}).get("indices") or {}
    for info in indices.values():
        if not isinstance(info, dict):
            continue
        if info.get("change_pct") is not None:
            idx_pct = float(info["change_pct"])
            idx_name = str(info.get("name") or idx_name)
            if "300" in idx_name or "沪深" in idx_name:
                break
    if idx_pct is None and macro_signals:
        raw = macro_signals.get("index_change_pct")
        if raw is not None:
            idx_pct = float(raw)
            idx_name = str(macro_signals.get("index_name") or "指数")
    if port_pct is None or idx_pct is None:
        return ""
    port = float(port_pct)
    if abs(port) <= 1.5:
        port *= 100.0
    alpha = port - idx_pct
    return f"组合 **{_fmt_pct(port)}** vs {idx_name} **{_fmt_pct(idx_pct)}**（超额 **{alpha:+.2f}%**）"


def _risk_summary(
    portfolio_summary: dict[str, Any],
    technical_scenarios: list[dict[str, Any]],
) -> str:
    for line in portfolio_summary.get("reason_lines") or []:
        text = str(line).strip()
        if text:
            return text[:160]
    for note in portfolio_summary.get("notes") or []:
        text = str(note).strip()
        if text:
            return text[:160]
    for sc in technical_scenarios:
        scenario_type = str(sc.get("scenario_type") or "")
        name = sc.get("name") or sc.get("code") or "—"
        if scenario_type == "upper_shadow":
            return f"⚠️ {name} 长上影 setup，关注 {sc.get('session_low')} 支撑"
        if scenario_type == "liquidity_shrink":
            return f"⚠️ {name} 缩量回调，警惕流动性继续萎缩"
        if scenario_type == "min_cash_ratio_cap":
            cash = sc.get("setup_cash_ratio")
            if cash is not None:
                return f"⚠️ 现金仓位 {float(cash):.0%} 触达 min_cash 约束"
    deploy = portfolio_summary.get("deploy_budget_line")
    if deploy:
        return str(deploy)[:160]
    cash_ratio = portfolio_summary.get("cash_ratio")
    if cash_ratio is not None and float(cash_ratio) >= 0.45:
        return f"风控：现金 **{float(cash_ratio):.0%}**，维持防守配置"
    return "风控：按 MSS / macro_veto 纪律执行，无额外阻断"


def _collect_symbol_rows(
    symbol_results: list[dict[str, Any]],
    portfolio_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    holdings = {
        _normalize_code(str(h.get("code") or "")): h
        for h in (portfolio_summary.get("holdings") or [])
        if isinstance(h, dict)
    }
    watchlist = {
        _normalize_code(str(w.get("code") or "")): w
        for w in (portfolio_summary.get("watchlist") or [])
        if isinstance(w, dict)
    }

    for entry in symbol_results:
        inner = entry.get("result") or {}
        snap = inner.get("snapshot") or {}
        verify = inner.get("verify") or {}
        code = _normalize_code(str(snap.get("code") or entry.get("code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        holding = holdings.get(code) or {}
        watch = watchlist.get(code) or {}
        shares = int(holding.get("shares") or 0)
        role = "持仓" if shares > 0 else "观察池"
        rows.append(
            {
                "code": code,
                "name": entry.get("name") or snap.get("name") or holding.get("name") or code,
                "price": holding.get("price") or snap.get("price") or verify.get("price_current"),
                "change_pct": holding.get("change_pct") if holding.get("change_pct") is not None else snap.get("change_pct"),
                "mss": snap.get("mss_final") or verify.get("mss_current"),
                "verdict": verify.get("verdict_current") or snap.get("verdict"),
                "shares": shares,
                "role": role,
                "sector": holding.get("sector") or watch.get("sector") or snap.get("sector"),
                "verify": verify,
                "snapshot": snap,
            }
        )

    for code, holding in holdings.items():
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "name": holding.get("name") or code,
                "price": holding.get("price"),
                "change_pct": holding.get("change_pct"),
                "mss": None,
                "verdict": "—",
                "shares": int(holding.get("shares") or 0),
                "role": "持仓",
                "sector": holding.get("sector"),
                "verify": {},
                "snapshot": {},
            }
        )
    for code, watch in watchlist.items():
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "name": watch.get("name") or code,
                "price": watch.get("price"),
                "change_pct": watch.get("change_pct"),
                "mss": None,
                "verdict": "—",
                "shares": 0,
                "role": "观察池",
                "sector": watch.get("sector"),
                "verify": {},
                "snapshot": {},
            }
        )
    return rows


def build_merged_close_card_context(
    *,
    symbol_results: list[dict[str, Any]],
    portfolio_summary: dict[str, Any],
    primary_snapshot: dict[str, Any],
    market_review: Optional[dict[str, Any]] = None,
    forecast_review: Optional[dict[str, Any]] = None,
    technical_watch: Optional[dict[str, Any]] = None,
    research_results: Optional[list[dict[str, Any]]] = None,
    improvements: Optional[dict[str, Any]] = None,
    narrative: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> CloseCardContext:
    verify_by_code: dict[str, dict[str, Any]] = {}
    for entry in symbol_results:
        verify = (entry.get("result") or {}).get("verify") or {}
        code = _normalize_code(str(verify.get("code") or entry.get("code") or ""))
        if code:
            verify_by_code[code] = verify

    scenarios = list((technical_watch or {}).get("scenarios") or [])
    if not scenarios:
        scenarios = list((technical_watch or {}).get("registered") or [])

    return CloseCardContext(
        portfolio_summary=portfolio_summary,
        symbol_rows=_collect_symbol_rows(symbol_results, portfolio_summary),
        verify_by_code=verify_by_code,
        forecast_review=forecast_review,
        market_review=market_review,
        macro_signals=primary_snapshot.get("macro_signals"),
        technical_scenarios=scenarios,
        research_results=list(research_results or []),
        improvements=improvements,
        narrative=narrative,
        primary_snapshot=primary_snapshot,
        settings=settings,
    )


def build_single_close_card_context(
    run_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> CloseCardContext:
    snap = run_result.get("snapshot") or {}
    pf_summary = run_result.get("portfolio_summary") or {}
    verify = run_result.get("verify") or {}
    code = _normalize_code(str(verify.get("code") or snap.get("code") or ""))
    symbol_results = [
        {
            "code": code,
            "name": snap.get("name") or verify.get("name"),
            "result": run_result,
        }
    ]
    technical = run_result.get("technical_watch") or {}
    return CloseCardContext(
        portfolio_summary=pf_summary,
        symbol_rows=_collect_symbol_rows(symbol_results, pf_summary),
        verify_by_code={code: verify} if code else {},
        forecast_review=run_result.get("forecast_review"),
        market_review=run_result.get("market_review"),
        macro_signals=snap.get("macro_signals"),
        technical_scenarios=list(technical.get("scenarios") or []),
        research_results=list(run_result.get("research") or []),
        improvements=run_result.get("close_improvements"),
        narrative=run_result.get("llm_narrative"),
        primary_snapshot=snap,
        settings=settings,
    )


def render_close_summary_markdown(ctx: CloseCardContext) -> str:
    pf = ctx.portfolio_summary
    lines: list[str] = []
    daily_pnl = pf.get("daily_pnl")
    if daily_pnl is not None:
        sign = "+" if float(daily_pnl) >= 0 else ""
        pct_s = _fmt_pct(pf.get("daily_pnl_pct"))
        lines.append(f"**当日盈亏：** {sign}¥{float(daily_pnl):,.0f}（{pct_s}）")
    elif pf.get("end_total") is not None:
        lines.append(f"**收盘净值：** ¥{float(pf['end_total']):,.0f}")

    bench = _benchmark_vs_portfolio(pf, ctx.market_review, ctx.macro_signals)
    if bench:
        lines.append(bench)

    if ctx.symbol_rows:
        lines.extend(["", "| 标的 | 代码 | 涨跌幅 | 角色 |", "|------|------|--------|------|"])
        for row in ctx.symbol_rows:
            lines.append(
                f"| {row.get('name')} | {row.get('code')} | {_fmt_pct(row.get('change_pct'))} "
                f"| {row.get('role')} |"
            )

    lines.extend(["", f"**风控：** {_risk_summary(pf, ctx.technical_scenarios)}"])
    return "\n".join(lines).strip()


def render_holdings_detail_markdown(ctx: CloseCardContext) -> str:
    if not ctx.symbol_rows:
        return ""
    lines = ["| 标的 | 收盘 | 涨跌 | MSS | 标签 | 股数 |", "|------|------|------|-----|------|------|"]
    for row in ctx.symbol_rows:
        price = row.get("price")
        price_s = f"¥{float(price):.2f}" if price is not None else "—"
        mss = row.get("mss")
        mss_s = f"{float(mss):.1f}" if mss is not None else "—"
        shares = int(row.get("shares") or 0)
        share_s = str(shares) if shares > 0 else "—"
        lines.append(
            f"| {row.get('name')} | {price_s} | {_fmt_pct(row.get('change_pct'))} | {mss_s} "
            f"| {row.get('verdict') or '—'} | {share_s} |"
        )
    return "\n".join(lines).strip()


def render_forecast_verify_markdown(ctx: CloseCardContext) -> str:
    forecast = ctx.forecast_review or {}
    evals = {str(e.get("code") or ""): e for e in (forecast.get("symbol_evals") or []) if isinstance(e, dict)}
    lines: list[str] = []

    if forecast:
        total = int(forecast.get("symbol_total") or 0)
        hits = int(forecast.get("symbol_hits") or 0)
        acc = forecast.get("accuracy")
        acc_s = f"{float(acc):.0%}" if acc is not None else "—"
        lines.append(f"**周预测命中率：** {hits}/{total}（{acc_s}）")
        if forecast.get("mss_hit") is not None:
            mark = "✅" if forecast.get("mss_hit") else "❌"
            lines.append(
                f"**组合 MSS：** {mark} 预测 {forecast.get('mss_predicted')} "
                f"vs 实际 {forecast.get('mss_actual')}"
            )
        if forecast.get("optimization_notes"):
            lines.append(f"- 校准：{forecast['optimization_notes'][0][:100]}")
        lines.append("")

    lines.extend(
        [
            "| 标的 | 涨跌验证 | MSS Δ | 周预测 | 命中 |",
            "|------|----------|-------|--------|------|",
        ]
    )
    dir_cn = {"up": "↑", "down": "↓", "flat": "→"}
    for row in ctx.symbol_rows:
        code = str(row.get("code") or "")
        verify = row.get("verify") or ctx.verify_by_code.get(code) or {}
        price_delta = verify.get("price_delta_pct")
        price_s = _fmt_pct(price_delta) if price_delta is not None else "—"
        mss_delta = verify.get("mss_delta")
        mss_s = f"{float(mss_delta):+.0f}" if mss_delta is not None else "—"
        ev = evals.get(code) or {}
        if ev:
            pred = dir_cn.get(ev.get("predicted_direction"), "→")
            pred_range = ev.get("predicted_range")
            lo = hi = None
            if isinstance(pred_range, (list, tuple)) and len(pred_range) == 2:
                lo, hi = pred_range
            range_s = f"{pred}[{float(lo):+.1f},{float(hi):+.1f}%]" if lo is not None and hi is not None else pred
            actual = _fmt_pct(ev.get("actual_change_pct"))
            forecast_s = f"{range_s} / 实际 {actual}"
            hit_s = "✅" if ev.get("hit") else "❌"
        else:
            within = verify.get("mss_within_prediction")
            if within is True:
                forecast_s = "MSS 区间命中"
                hit_s = "✅"
            elif within is False:
                forecast_s = "MSS 区间偏离"
                hit_s = "❌"
            else:
                forecast_s = "—"
                hit_s = "—"
        lines.append(
            f"| {row.get('name')} | {price_s} | {mss_s} | {forecast_s} | {hit_s} |"
        )

    devs: list[str] = []
    for verify in ctx.verify_by_code.values():
        for dev in verify.get("deviations") or []:
            text = str(dev).strip()
            if text and text not in devs:
                devs.append(text[:100])
    if devs:
        lines.extend(["", "**偏差：**"])
        for dev in devs[:3]:
            lines.append(f"- {dev}")
    return "\n".join(lines).strip()


def _scenario_signal_line(sc: dict[str, Any]) -> str:
    scenario_type = str(sc.get("scenario_type") or "upper_shadow")
    name = sc.get("name") or sc.get("code") or "—"
    code = sc.get("code") or ""
    if scenario_type == "upper_shadow":
        low = sc.get("session_low")
        high = sc.get("session_high")
        return f"**{name}** 长上影 · 支撑 **{low}** / 压力 **{high}**"
    if scenario_type == "liquidity_shrink":
        return f"**{name}** 缩量回调 · 收 **{sc.get('session_close')}**"
    if scenario_type == "limit_up_shrink_pullback":
        return f"**{name} {code}** 涨停后缩量"
    if scenario_type == "mss_trend":
        return f"**{name}** MSS 走弱 · {sc.get('setup_mss_low')}~{sc.get('setup_mss_high')}"
    if scenario_type == "min_cash_ratio_cap":
        cash = sc.get("setup_cash_ratio")
        return f"**组合** min_cash 约束 · 现金 **{float(cash):.0%}**" if cash is not None else "**组合** min_cash 约束"
    return f"**{name}** {scenario_type}"


def render_key_signals_markdown(ctx: CloseCardContext) -> str:
    lines: list[str] = []
    if ctx.technical_scenarios:
        lines.append("**技术情景**")
        for sc in ctx.technical_scenarios[:6]:
            lines.append(f"- {_scenario_signal_line(sc)}")
            bear = (sc.get("bearish") or {}).get("label")
            bull = (sc.get("bullish") or {}).get("label")
            if bear:
                lines.append(f"  - 📉 {bear[:80]}")
            if bull:
                lines.append(f"  - 📈 {bull[:80]}")
        lines.append("")

    sectors = ctx.portfolio_summary.get("sector_weights") or []
    if sectors:
        parts = [
            f"**{s.get('sector') or '—'}** {float(s.get('weight_pct') or 0):.0f}%"
            for s in sectors[:3]
            if isinstance(s, dict)
        ]
        if parts:
            lines.append(f"**持仓板块：** {' · '.join(parts)}")

    sa = (ctx.market_review or {}).get("sector_analysis") or {}
    if sa.get("mainline_type"):
        lines.append(
            f"**板块主线：** {sa.get('mainline_type')} — {(sa.get('reasoning') or '')[:80]}"
        )

    cmp_ = (ctx.market_review or {}).get("comparison") or {}
    vs_y = cmp_.get("vs_yesterday") or {}
    if vs_y:
        lines.append(
            f"**vs 昨日：** 涨停 {int(vs_y.get('limit_up_delta') or 0):+d} · "
            f"跌停 {int(vs_y.get('limit_down_delta') or 0):+d} · "
            f"北向 {float(vs_y.get('northbound_delta_yi') or 0):+.1f} 亿"
        )
    return "\n".join(lines).strip() or "暂无额外关键信号"


def _holding_codes(portfolio_summary: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for row in portfolio_summary.get("holdings") or []:
        if isinstance(row, dict):
            code = _normalize_code(str(row.get("code") or ""))
            if code:
                codes.add(code)
    return codes


def render_hot_research_markdown(ctx: CloseCardContext) -> str:
    holding_codes = _holding_codes(ctx.portfolio_summary)
    lines: list[str] = []
    snap = dict(ctx.primary_snapshot or {})
    snap["portfolio"] = {
        **((snap.get("portfolio") or {})),
        "holdings": ctx.portfolio_summary.get("holdings") or [],
        "watchlist": [],
    }

    from agent_reach.daily_run.symbol_news import render_symbol_news_markdown

    for row in ctx.symbol_rows:
        if row.get("role") != "持仓":
            continue
        code = str(row.get("code") or "")
        if code not in holding_codes:
            continue
        news = render_symbol_news_markdown(code, snap, name=str(row.get("name") or ""))
        if news:
            lines.append(news)
            lines.append("")

    macro = ctx.macro_signals or {}
    from agent_reach.daily_run.xueqiu_hot_display import (
        render_portfolio_hot_post_overlap_markdown,
        render_portfolio_hot_stock_overlap_markdown,
    )

    stock_matches = [
        m
        for m in (macro.get("portfolio_hot_stocks") or [])
        if _normalize_code(str(m.get("code") or "")) in holding_codes
    ]
    post_matches = macro.get("portfolio_hot_posts") or []
    stock_md = render_portfolio_hot_stock_overlap_markdown(stock_matches)
    post_md = render_portfolio_hot_post_overlap_markdown(post_matches)
    if stock_md:
        lines.extend(stock_md.splitlines())
        lines.append("")
    if post_md:
        lines.extend(post_md.splitlines())
        lines.append("")

    ok_research = [
        r
        for r in ctx.research_results
        if r.get("success") and (r.get("summary") or "").strip()
    ]
    if ok_research:
        lines.append("**🔍 Exa 调研（持仓）**")
        for row in ok_research[:4]:
            label = row.get("label") or "调研"
            summary = str(row.get("summary") or "").strip().splitlines()[0][:160]
            lines.append(f"- **{label}：** {summary}")
    return "\n".join(lines).strip() or "暂无与持仓直接相关的热点/调研"


def render_tomorrow_focus_markdown(ctx: CloseCardContext) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    for row in ctx.symbol_rows:
        verify = row.get("verify") or ctx.verify_by_code.get(str(row.get("code") or "")) or {}
        for rec in verify.get("recommendations") or []:
            text = str(rec).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(f"- **{row.get('name')}：** {text[:120]}")

    for sc in ctx.technical_scenarios[:5]:
        name = sc.get("name") or sc.get("code") or "—"
        bull = (sc.get("bullish") or {}).get("label")
        bear = (sc.get("bearish") or {}).get("label")
        if bull:
            key = f"{name}:bull:{bull}"
            if key not in seen:
                seen.add(key)
                lines.append(f"- **{name} 触发做多：** {bull[:100]}")
        if bear:
            key = f"{name}:bear:{bear}"
            if key not in seen:
                seen.add(key)
                lines.append(f"- **{name} 触发减仓：** {bear[:100]}")

    narrative = ctx.narrative or {}
    if not narrative.get("skipped"):
        for item in narrative.get("focus_points") or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                lines.append(f"- {text[:120]}")

    for item in (ctx.improvements or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get("detail") or item.get("title") or "").strip()
        if not detail or detail in seen:
            continue
        if "明日" in detail or "早盘" in detail or item.get("priority") == "high":
            seen.add(detail)
            lines.append(f"- {detail[:120]}")

    deploy = ctx.portfolio_summary.get("deploy_budget_line")
    if deploy and str(deploy) not in seen:
        lines.append(f"- {str(deploy)[:120]}")
    return "\n".join(lines[:8]).strip() or "- 按 MSS 与 macro_veto 纪律执行，明日早盘再确认"


_CARD_RENDERERS = {
    "close_summary": render_close_summary_markdown,
    "holdings_detail": render_holdings_detail_markdown,
    "forecast_verify": render_forecast_verify_markdown,
    "key_signals": render_key_signals_markdown,
    "hot_research": render_hot_research_markdown,
    "tomorrow_focus": render_tomorrow_focus_markdown,
}


def render_close_card_sections(ctx: CloseCardContext) -> list[ReportSection]:
    sections: list[ReportSection] = []
    for category in CLOSE_CARD_ORDER:
        renderer = _CARD_RENDERERS[category]
        body = renderer(ctx)
        if not (body or "").strip():
            continue
        sections.append(ReportSection(category=category, title="", body=body.strip()))
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        label = CLOSE_CARD_LABELS.get(sec.category, sec.category)
        sec.title = f"{label} {i}/{total}"
    return sections
