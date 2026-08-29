# -*- coding: utf-8
"""Weekly report signal cards — overview, holdings, strategy, outlook."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.weekly_card_metrics import (
    _DEFAULT_BENCHMARK_KEY,
    _DEFAULT_BENCHMARK_NAME,
    fetch_benchmark_weekly_return,
)

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_SEVERITY_HIGH = "🔴 高"
_SEVERITY_MED = "🟡 中"
_SEVERITY_LOW = "🟢 低"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if float(value) >= 0 else ""
    return f"{sign}{float(value):.1f}%"


def _weekday_label(ds: str) -> str:
    try:
        return _WEEKDAY_CN[date.fromisoformat(ds[:10]).weekday()]
    except ValueError:
        return ds[:10]


def fetch_benchmark_return_between(
    start: date,
    end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    bench = fetch_benchmark_weekly_return(start, end, settings=settings)
    if bench.get("ok") and bench.get("return_pct") is not None:
        return float(bench["return_pct"])
    return None


def _portfolio_total_on_day(
    day: date,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history

    rows = load_daily_pnl_history(start=day, end=day, settings=settings)
    for row in reversed(rows):
        if row.end_total is not None:
            return float(row.end_total)
        if row.start_total is not None:
            return float(row.start_total)
    return None


def portfolio_return_between(
    start: date,
    end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
    end_total_hint: Optional[float] = None,
    start_total_hint: Optional[float] = None,
) -> Optional[float]:
    start_total = start_total_hint
    end_total = end_total_hint
    if start_total is None:
        from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history

        start_rows = load_daily_pnl_history(start=start, end=start, settings=settings)
        if start_rows:
            start_total = start_rows[0].start_total or start_rows[0].end_total
        if start_total is None:
            start_total = _portfolio_total_on_day(start, settings=settings)
    if end_total is None:
        end_total = _portfolio_total_on_day(end, settings=settings)
    if start_total is None or end_total is None or float(start_total) <= 0:
        return None
    return round((float(end_total) - float(start_total)) / float(start_total) * 100.0, 2)


def build_performance_overview_table(
    *,
    week_start: date,
    week_end: date,
    start_total: Optional[float],
    end_total: Optional[float],
    weekly_metrics: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    week_port = weekly_metrics.get("absolute_return_pct")
    if week_port is None:
        week_port = portfolio_return_between(
            week_start,
            week_end,
            settings=settings,
            start_total_hint=start_total,
            end_total_hint=end_total,
        )
    bench = weekly_metrics.get("benchmark") or {}
    week_bench = bench.get("return_pct") if bench.get("ok") else None
    week_excess = weekly_metrics.get("excess_return_pct")
    if week_excess is None and week_port is not None and week_bench is not None:
        week_excess = round(float(week_port) - float(week_bench), 2)

    four_week_start = week_start - timedelta(days=28)
    four_port = portfolio_return_between(
        four_week_start,
        week_end,
        settings=settings,
        end_total_hint=end_total,
    )
    four_bench = fetch_benchmark_return_between(four_week_start, week_end, settings=settings)
    four_excess = (
        round(float(four_port) - float(four_bench), 2)
        if four_port is not None and four_bench is not None
        else None
    )

    ytd_start = date(week_end.year, 1, 1)
    ytd_port = portfolio_return_between(ytd_start, week_end, settings=settings, end_total_hint=end_total)
    ytd_bench = fetch_benchmark_return_between(ytd_start, week_end, settings=settings)
    ytd_excess = (
        round(float(ytd_port) - float(ytd_bench), 2) if ytd_port is not None and ytd_bench is not None else None
    )

    rows = [
        {
            "metric": "组合收益率",
            "week": week_port,
            "four_weeks": four_port,
            "ytd": ytd_port,
        },
        {
            "metric": f"基准（{_DEFAULT_BENCHMARK_NAME}）",
            "week": week_bench,
            "four_weeks": four_bench,
            "ytd": ytd_bench,
        },
        {
            "metric": "超额收益",
            "week": week_excess,
            "four_weeks": four_excess,
            "ytd": ytd_excess,
        },
    ]
    return {
        "rows": rows,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "four_week_start": four_week_start.isoformat(),
        "ytd_start": ytd_start.isoformat(),
    }


def build_holdings_contribution_table(
    holdings: list[dict[str, Any]],
    *,
    start_total: Optional[float] = None,
) -> list[dict[str, Any]]:
    if not holdings:
        return []
    base = float(start_total) if start_total and start_total > 0 else sum(
        float(h.get("market_value") or 0) for h in holdings
    )
    rows: list[dict[str, Any]] = []
    for h in holdings:
        mv = float(h.get("market_value") or 0)
        weight = round(mv / base * 100.0, 1) if base > 0 else 0.0
        week_pct = _optional_float(h.get("week_chg_pct"))
        contribution = round(weight * float(week_pct or 0) / 100.0, 2) if week_pct is not None else None
        rows.append(
            {
                "code": h.get("code"),
                "name": h.get("name") or h.get("code"),
                "week_chg_pct": week_pct,
                "weight_pct": weight,
                "contribution_pct": contribution,
            }
        )
    rows.sort(key=lambda r: float(r.get("week_chg_pct") or -999), reverse=True)
    if rows:
        best = max(rows, key=lambda r: float(r.get("contribution_pct") or -999))
        worst = min(rows, key=lambda r: float(r.get("contribution_pct") or 999))
        for row in rows:
            tags: list[str] = []
            if row is best and float(row.get("contribution_pct") or 0) > 0:
                tags.append("🌟 最大贡献")
            if row is worst and float(row.get("contribution_pct") or 0) < 0:
                tags.append("⚠️ 拖后腿")
            row["tags"] = " ".join(tags)
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
    return rows


def build_position_change_summary(
    *,
    start_total: Optional[float],
    end_total: Optional[float],
    start_stock_mv: Optional[float],
    end_stock_mv: Optional[float],
    trade_log: list[dict[str, Any]],
    daily_totals: list[dict[str, Any]],
) -> dict[str, Any]:
    start_exposure: Optional[float] = None
    end_exposure: Optional[float] = None
    if start_total and start_stock_mv is not None and float(start_total) > 0:
        start_exposure = round(float(start_stock_mv) / float(start_total) * 100.0, 1)
    if end_total and end_stock_mv is not None and float(end_total) > 0:
        end_exposure = round(float(end_stock_mv) / float(end_total) * 100.0, 1)

    reasons: list[str] = []
    for row in trade_log:
        side = str(row.get("side") or "")
        name = str(row.get("name") or row.get("code") or "")
        ds = str(row.get("date") or "")[:10]
        wd = _weekday_label(ds) if ds else ""
        amount = _optional_float(row.get("amount")) or 0.0
        if not name or not side:
            continue
        if end_total and end_total > 0 and amount > 0:
            delta = round(amount / float(end_total) * 100.0, 1)
            if side == "买":
                reasons.append(f"{wd}加仓{name} +{delta}%")
            elif side == "卖":
                reasons.append(f"{wd}减仓{name} -{delta}%")

    market_part = ""
    if (
        start_exposure is not None
        and end_exposure is not None
        and start_total
        and end_total
        and float(start_total) > 0
    ):
        trade_effect = sum(
            (float(r.get("amount") or 0) / float(end_total) * 100.0)
            * (-1 if r.get("side_raw") == "buy" else 1 if r.get("side_raw") == "sell" else 0)
            for r in trade_log
        )
        implied_market = round(end_exposure - start_exposure - trade_effect, 1)
        if abs(implied_market) >= 0.1:
            market_part = f"其余为市值波动 {implied_market:+.1f}%"

    closes = sorted(
        [
            (str(r.get("date") or ""), float(r["total"]))
            for r in daily_totals
            if r.get("job") == "close" and r.get("total") is not None
        ],
        key=lambda x: x[0],
    )
    trend = ""
    if len(closes) >= 2:
        exp_series: list[str] = []
        for ds, total in closes:
            if total <= 0:
                continue
            stock_est = end_stock_mv if ds == closes[-1][0] else None
            if stock_est is None and end_total and end_stock_mv is not None:
                ratio = end_stock_mv / end_total
                stock_est = total * ratio
            if stock_est is None:
                continue
            exp = round(stock_est / total * 100.0)
            exp_series.append(f"{ds[5:]}:{exp}%")
        if exp_series:
            trend = " → ".join(exp_series[:5])

    reason_text = "，".join(reasons[:4])
    if market_part:
        reason_text = (reason_text + "，" if reason_text else "") + market_part

    return {
        "start_exposure_pct": start_exposure,
        "end_exposure_pct": end_exposure,
        "reason_text": reason_text or "本周无 ledger 调仓，变化主要来自市值波动",
        "trend_text": trend,
    }


def build_strategy_validation(
    *,
    trade_log: list[dict[str, Any]],
    trade_pnl_detail: dict[str, Any],
    prediction_verification: dict[str, Any],
    sell_rules_whatif: Optional[dict[str, Any]] = None,
    buy_rules_whatif: Optional[dict[str, Any]] = None,
    prior_week_win_rate: Optional[float] = None,
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []

    for sell in trade_pnl_detail.get("sells") or []:
        if not isinstance(sell, dict):
            continue
        pnl = _optional_float(sell.get("realized_pnl"))
        signals.append(
            {
                "date": str(sell.get("date") or "")[:10],
                "name": sell.get("name") or sell.get("code"),
                "signal": "卖出信号",
                "outcome": f"已实现 ¥{float(pnl or 0):+,.0f}",
                "hit": pnl is not None and pnl >= 0,
            }
        )

    for case in prediction_verification.get("featured_cases") or []:
        signals.append(
            {
                "date": str(case.get("date") or "")[:10],
                "name": case.get("name"),
                "signal": str(case.get("type") or "预测"),
                "outcome": str(case.get("detail") or ""),
                "hit": bool(case.get("hit")),
            }
        )

    for wf, label in ((sell_rules_whatif, "卖出规则"), (buy_rules_whatif, "买入规则")):
        if not wf or wf.get("skipped"):
            continue
        for row in wf.get("rows") or []:
            if not isinstance(row, dict):
                continue
            code = row.get("code") or row.get("name")
            if not code:
                continue
            actual = _optional_float(row.get("actual_realized_pnl") or row.get("actual_bought"))
            hypo = _optional_float(row.get("hypothetical_realized_pnl") or row.get("hypothetical_bought"))
            hit = None
            if actual is not None and hypo is not None:
                hit = actual >= hypo
            signals.append(
                {
                    "date": str(wf.get("as_of") or "")[:10],
                    "name": row.get("name") or code,
                    "signal": label,
                    "outcome": f"实际 {actual if actual is not None else '—'} vs 规则 {hypo if hypo is not None else '—'}",
                    "hit": hit,
                }
            )

    scored = [s for s in signals if s.get("hit") is not None]
    total = len(scored)
    wins = sum(1 for s in scored if s.get("hit"))
    win_rate = round(wins / total * 100.0, 1) if total else None

    profits = [float(s.get("_pnl", 0)) for s in signals if s.get("_pnl") is not None]
    for sell in trade_pnl_detail.get("sells") or []:
        pnl = _optional_float(sell.get("realized_pnl"))
        if pnl is not None:
            profits.append(float(pnl))
    win_vals = [p for p in profits if p > 0]
    loss_vals = [abs(p) for p in profits if p < 0]
    pl_ratio = round(sum(win_vals) / len(win_vals) / (sum(loss_vals) / len(loss_vals)), 2) if win_vals and loss_vals else None

    suggestions: list[str] = []
    if win_rate is not None and win_rate < 50:
        suggestions.append(f"本周策略胜率 {win_rate:.0f}% 低于 50%，建议复盘信号触发条件")
    if prior_week_win_rate is not None and win_rate is not None:
        if win_rate < 50 and prior_week_win_rate < 50:
            suggestions.append("连续 2 周胜率 < 50%，建议暂停自动调仓或下调 aggressive_entry / deploy_ratio")
    if not suggestions and win_rate is not None:
        suggestions.append(f"本周策略胜率 {win_rate:.0f}%，维持现有参数并跟踪盈亏比")

    return {
        "signals": signals[:12],
        "signal_count": total,
        "win_count": wins,
        "win_rate_pct": win_rate,
        "profit_loss_ratio": pl_ratio,
        "suggestions": suggestions[:2],
    }


def _prior_week_win_rate(week_start: date, *, settings: Optional[dict[str, Any]] = None) -> Optional[float]:
    from agent_reach.daily_run.weekly_content_scope import summarize_week_prediction_verification
    from agent_reach.daily_run.weekly_report import _load_week_manifests

    prior_end = week_start - timedelta(days=1)
    while prior_end.weekday() != 4:
        prior_end -= timedelta(days=1)
    prior_start = prior_end - timedelta(days=4)
    manifests = _load_week_manifests(prior_start, prior_end)
    if not manifests:
        return None
    data = summarize_week_prediction_verification(
        manifests,
        week_start=prior_start,
        week_end=prior_end,
    )
    rows = data.get("summary_rows") or []
    sym = next((r for r in rows if r.get("type") == "标的涨跌"), None)
    if sym and sym.get("total"):
        return float(sym.get("accuracy_pct"))
    return None


def build_next_week_outlook(
    *,
    week_end: date,
    holdings: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
    watchlist_intel: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.close_morning_handoff import load_close_handoff
    from agent_reach.daily_run.prior_close import load_close_baseline
    from agent_reach.daily_run.week_forecast import next_trading_week_range

    handoff = load_close_handoff(close_day=week_end, settings=settings) or {}
    focus_items = list(handoff.get("tomorrow_focus") or [])
    positions = dict(handoff.get("positions") or {})

    plan_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for item in focus_items:
        code = _normalize_code(str(item.get("code") or ""))
        name = str(item.get("name") or code or "—")
        text = str(item.get("text") or "")
        if not text:
            continue
        action = "持有"
        if any(k in text for k in ("减仓", "卖出", "清仓", "止损")):
            action = "减仓"
        elif any(k in text for k in ("加仓", "买入", "新建仓")):
            action = "买入" if "新建" not in text else "新建仓"
        pos = positions.get(code) or {}
        cur_weight = _optional_float(pos.get("weight_pct"))
        target = f"维持 {cur_weight:.0f}%" if cur_weight is not None else "—"
        if action == "减仓" and cur_weight is not None:
            target = f"{cur_weight:.0f}% → {max(cur_weight / 2, 5):.0f}%"
        elif action in ("买入", "新建仓"):
            target = f"{cur_weight or 0:.0f}% → {min((cur_weight or 0) + 10, 25):.0f}%"
        stop = None
        if code:
            baseline = load_close_baseline(code, target_day=week_end, settings=settings)
            stop = _optional_float((baseline or {}).get("stop_loss_price"))
        plan_rows.append(
            {
                "name": name,
                "code": code,
                "action": action,
                "trigger": text[:48],
                "target_weight": target,
                "stop_loss": f"{stop:.2f} 元" if stop else "—",
            }
        )
        if code:
            seen_codes.add(code)

    for h in holdings:
        code = _normalize_code(str(h.get("code") or ""))
        if not code or code in seen_codes:
            continue
        weight = None
        if handoff.get("portfolio_total") and h.get("market_value"):
            weight = round(float(h["market_value"]) / float(handoff["portfolio_total"]) * 100.0, 1)
        baseline = load_close_baseline(code, target_day=week_end, settings=settings)
        stop = _optional_float((baseline or {}).get("stop_loss_price"))
        plan_rows.append(
            {
                "name": h.get("name") or code,
                "code": code,
                "action": "持有",
                "trigger": "—",
                "target_weight": f"维持 {weight:.0f}%" if weight is not None else "—",
                "stop_loss": f"{stop:.2f} 元" if stop else "—",
            }
        )
        seen_codes.add(code)

    next_start, next_end = next_trading_week_range(week_end + timedelta(days=1))
    risk_rows: list[dict[str, Any]] = []
    intel = watchlist_intel or {}
    for code, block in intel.items():
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or code)
        for ann in block.get("announcements") or []:
            if not isinstance(ann, dict):
                continue
            title = str(ann.get("title") or "").strip()
            pub = str(ann.get("date") or ann.get("pub_date") or "")[:10]
            if not title:
                continue
            risk_rows.append(
                {
                    "date": pub or next_start.isoformat(),
                    "event": f"{name} {title[:40]}",
                    "scope": "个股",
                    "severity": _SEVERITY_MED,
                }
            )

    risk_rows.append(
        {
            "date": next_end.isoformat(),
            "event": "股指期货交割",
            "scope": "大盘波动",
            "severity": _SEVERITY_MED,
        }
    )
    for item in handoff.get("watch_risks") or []:
        text = str(item.get("text") or "")
        if not text:
            continue
        risk_rows.append(
            {
                "date": next_start.isoformat(),
                "event": text[:60],
                "scope": "持仓" if item.get("code") else "组合",
                "severity": _SEVERITY_MED,
            }
        )

    risk_rows = risk_rows[:8]
    return {
        "operation_plan": plan_rows[:8],
        "risk_calendar": risk_rows,
        "next_week_start": next_start.isoformat(),
        "next_week_end": next_end.isoformat(),
    }


def render_performance_overview_markdown(table: dict[str, Any]) -> list[str]:
    if not table or not table.get("rows"):
        return []
    lines = [
        "## 📊 收益总览",
        "",
        "| 指标 | 本周 | 近4周 | 年初至今 |",
        "|------|------|-------|----------|",
    ]
    for row in table["rows"]:
        lines.append(
            f"| {row.get('metric')} | {_fmt_pct(row.get('week'))} | "
            f"{_fmt_pct(row.get('four_weeks'))} | {_fmt_pct(row.get('ytd'))} |"
        )
    lines.append("")
    return lines


def render_position_change_markdown(summary: dict[str, Any]) -> list[str]:
    if not summary:
        return []
    start_e = summary.get("start_exposure_pct")
    end_e = summary.get("end_exposure_pct")
    if start_e is None and end_e is None:
        return []
    lines = ["## 📈 仓位变化"]
    if start_e is not None and end_e is not None:
        lines.append(f"- **股票仓位：** {float(start_e):.0f}% → {float(end_e):.0f}%")
    if summary.get("reason_text"):
        lines.append(f"- **变化原因：** {summary['reason_text']}")
    if summary.get("trend_text"):
        lines.append(f"- **周内趋势：** {summary['trend_text']}")
    lines.append("")
    return lines


def render_holdings_contribution_markdown(rows: list[dict[str, Any]], *, as_of: str = "") -> list[str]:
    lines = ["## 📋 持仓周度复盘"]
    if as_of:
        lines.append(f"- **{as_of}**")
    if not rows:
        lines.append("- 暂无持仓")
        lines.append("")
        return lines
    lines.extend(
        [
            "",
            "| 排名 | 股票 | 周涨跌幅 | 持仓权重 | 收益贡献 | 标签 |",
            "|:----:|------|---------|---------|---------|------|",
        ]
    )
    for row in rows:
        chg = _fmt_pct(row.get("week_chg_pct"))
        contrib = _fmt_pct(row.get("contribution_pct"))
        weight = f"{float(row.get('weight_pct') or 0):.0f}%"
        tags = str(row.get("tags") or "")
        lines.append(
            f"| {row.get('rank')} | {row.get('name')} | {chg} | {weight} | {contrib} | {tags} |"
        )
    lines.append("")
    return lines


def render_strategy_validation_markdown(data: dict[str, Any]) -> list[str]:
    if not data:
        return []
    lines = ["## ✅ 策略验证", ""]
    total = int(data.get("signal_count") or 0)
    wins = int(data.get("win_count") or 0)
    win_rate = data.get("win_rate_pct")
    win_s = f"{float(win_rate):.1f}%" if win_rate is not None else "—"
    lines.append(f"- **策略胜率：** 本周触发 {total} 个信号，盈利 {wins} 个，胜率 **{win_s}**")
    pl = data.get("profit_loss_ratio")
    if pl is not None:
        lines.append(f"- **盈亏比：** 平均盈利 / 平均亏损 = **{float(pl):.2f}**")

    signals = data.get("signals") or []
    if signals:
        lines.extend(["", "**本周策略信号 vs 实际走势：**"])
        for sig in signals[:8]:
            mark = "✅" if sig.get("hit") else "❌" if sig.get("hit") is False else "—"
            lines.append(
                f"- {mark} {_weekday_label(str(sig.get('date') or ''))} "
                f"**{sig.get('name')}** · {sig.get('signal')} · {sig.get('outcome')}"
            )

    suggestions = data.get("suggestions") or []
    if suggestions:
        lines.extend(["", "**策略调整建议：**"])
        for note in suggestions:
            lines.append(f"- {note}")
    lines.append("")
    return lines


def render_next_week_outlook_markdown(outlook: dict[str, Any]) -> list[str]:
    if not outlook:
        return []
    lines = ["## 🔭 下周展望", ""]
    plan = outlook.get("operation_plan") or []
    if plan:
        lines.extend(
            [
                "### 操作计划",
                "",
                "| 股票 | 操作 | 触发条件 | 目标仓位 | 止损位 |",
                "|------|------|----------|----------|--------|",
            ]
        )
        for row in plan:
            lines.append(
                f"| {row.get('name')} | {row.get('action')} | {row.get('trigger')} | "
                f"{row.get('target_weight')} | {row.get('stop_loss')} |"
            )
        lines.append("")

    risks = outlook.get("risk_calendar") or []
    if risks:
        lines.extend(
            [
                "### 下周风险日历",
                "",
                "| 日期 | 事件 | 影响范围 | 严重程度 |",
                "|------|------|----------|:--------:|",
            ]
        )
        for row in risks:
            ds = str(row.get("date") or "")
            label = _weekday_label(ds) if ds else "—"
            lines.append(
                f"| {label} {ds[5:] if len(ds) >= 10 else ds} | {row.get('event')} | "
                f"{row.get('scope')} | {row.get('severity')} |"
            )
        lines.append("")
    return lines
