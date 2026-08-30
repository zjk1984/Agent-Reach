# -*- coding: utf-8
"""Weekly report content scope — dedupe daily detail, macro, market, prediction cards."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.morning_content_scope import (
    collect_macro_headline_candidates,
    infer_affected_sectors,
    infer_impact_label,
)
from agent_reach.daily_run.snapshot_builder import _normalize_code

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_PRED_TYPES = ("标的涨跌", "MSS区间", "趋势预测", "反转预测")


def _weekday_label(ds: str) -> str:
    try:
        return _WEEKDAY_CN[date.fromisoformat(ds[:10]).weekday()]
    except ValueError:
        return ds[:10]


def _close_card_ref(ds: str) -> str:
    return f"详见{_weekday_label(ds)}收盘卡片"


def _manifest_close_forecast(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = record.get("payload") or {}
    result = payload.get("result") or {}
    fr = result.get("forecast_review")
    if isinstance(fr, dict):
        return fr
    for sr in payload.get("symbol_results") or []:
        inner = (sr.get("result") or {})
        fr = inner.get("forecast_review")
        if isinstance(fr, dict):
            return fr
    return None


def _manifest_verifies(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    out: list[dict[str, Any]] = []
    result = payload.get("result") or {}
    verify = result.get("verify")
    if isinstance(verify, dict):
        out.append(verify)
    for sr in payload.get("symbol_results") or []:
        v = (sr.get("result") or {}).get("verify")
        if isinstance(v, dict):
            out.append(v)
    return out


def enrich_trade_log_with_pnl(
    trade_log: list[dict[str, Any]],
    trade_pnl_detail: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    detail = trade_pnl_detail or {}
    sell_map: dict[tuple[str, str, int], float] = {}
    for row in detail.get("sells") or []:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("date") or "")[:10],
            _normalize_code(str(row.get("code") or "")),
            int(row.get("shares") or 0),
        )
        sell_map[key] = float(row.get("realized_pnl") or 0)

    rows: list[dict[str, Any]] = []
    for entry in trade_log:
        side_raw = str(entry.get("side_raw") or "")
        name = str(entry.get("name") or entry.get("code") or "")
        shares = int(entry.get("shares") or 0)
        price = entry.get("price")
        side = str(entry.get("side") or "")
        if price is not None and shares:
            op = f"{side}{name} {shares}股@{float(price):.2f}"
        elif shares:
            op = f"{side}{name} {shares}股"
        else:
            op = f"{side}{name}"
        pnl: Optional[float] = None
        if side_raw == "sell":
            key = (
                str(entry.get("date") or "")[:10],
                _normalize_code(str(entry.get("code") or "")),
                shares,
            )
            if key in sell_map:
                pnl = sell_map[key]
        row = dict(entry)
        row["operation"] = op
        row["pnl"] = pnl
        rows.append(row)
    return rows


def render_weekly_trade_log_compact_markdown(
    trade_log: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    *,
    source_note: str = "",
) -> list[str]:
    note = source_note or "- _来源：trade ledger 实际成交；详细数据见各日收盘卡片_"
    lines = ["## 📝 本周交易日志", note]
    if not trade_log:
        lines.append("- 本周无 ledger 成交记录")
    else:
        lines.extend(
            [
                "",
                "| 日期 | 操作 | 盈亏 |",
                "|------|------|------|",
            ]
        )
        for row in trade_log[:25]:
            pnl = row.get("pnl")
            if pnl is not None:
                pnl_s = f"¥{float(pnl):+,.0f}"
            else:
                pnl_s = "—"
            lines.append(f"| {row.get('date')} | {row.get('operation')} | {pnl_s} |")
    if reconciliation:
        mark = "✅" if reconciliation.get("ok") else "❌"
        lines.append("")
        lines.append(
            f"- **流水校验 {mark}（现金）：** 买入 ¥{float(reconciliation.get('buy_total') or 0):,.0f} "
            f"- 卖出 ¥{float(reconciliation.get('sell_total') or 0):,.0f} "
            f"= 现金流出 ¥{float(reconciliation.get('identity_rhs') or 0):,.0f}"
        )
    lines.append("")
    return lines


def summarize_week_key_events(
    manifests: list[dict[str, Any]],
    *,
    trades: Optional[list[dict[str, Any]]] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """One-sentence capital events with close-card refs — no daily analysis replay."""
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(ds: str, text: str, *, priority: int = 0) -> None:
        key = f"{ds}|{text[:40]}"
        if not text.strip() or key in seen:
            return
        seen.add(key)
        events.append(
            {
                "date": ds,
                "weekday": _weekday_label(ds),
                "text": text.strip(),
                "ref": _close_card_ref(ds),
                "priority": priority,
            }
        )

    close_rows = sorted(
        [m for m in manifests if m.get("job") == "close"],
        key=lambda m: str(m.get("_run_date") or ""),
    )
    for record in close_rows:
        ds = str(record.get("_run_date") or "")[:10]
        if not ds:
            continue
        for verify in _manifest_verifies(record):
            name = str(verify.get("name") or verify.get("code") or "")
            delta = verify.get("price_delta_pct")
            if delta is not None and abs(float(delta)) >= 5.0:
                direction = "涨停" if float(delta) >= 9.5 else "跌停" if float(delta) <= -9.5 else "大波动"
                _add(
                    ds,
                    f"{_weekday_label(ds)}{name}{direction}（{float(delta):+.1f}%）",
                    priority=abs(float(delta)),
                )
            for dev in verify.get("deviations") or []:
                text = str(dev).strip()
                if text and len(text) >= 8:
                    _add(ds, f"{_weekday_label(ds)}{text[:72]}", priority=3)

    for entry in trades or []:
        ds = str(entry.get("at") or entry.get("date") or "")[:10]
        for action in entry.get("actions") or []:
            if not isinstance(action, dict):
                continue
            side = "买入" if action.get("side") == "buy" else "卖出"
            name = str(action.get("name") or action.get("code") or "")
            shares = action.get("shares")
            if shares:
                _add(ds, f"{_weekday_label(ds)}{side}{name} {int(shares)}股", priority=2)

    events.sort(key=lambda e: (-float(e.get("priority") or 0), str(e.get("date") or "")))
    return events[:limit]


def render_week_key_events_markdown(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return []
    lines = ["## 📌 本周关键事件", ""]
    for ev in events:
        lines.append(f"- {ev.get('text')} — _{ev.get('ref')}_")
    lines.append("")
    return lines


def _sector_change_map(
    sector_snapshot: dict[str, Any],
    holdings: list[dict[str, Any]],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in sector_snapshot.get("sectors") or []:
        sector = str(row.get("sector") or "")
        avg = row.get("avg_change_pct")
        if sector and avg is not None:
            out[sector] = float(avg)
    for h in holdings:
        sector = str(h.get("sector") or "未分类")
        chg = h.get("week_chg_pct")
        if chg is not None and sector not in out:
            out[sector] = float(chg)
    return out


def build_weekly_macro_brief(
    *,
    portfolio: dict[str, Any],
    macro_signals: Optional[dict[str, Any]] = None,
    sources: Optional[dict[str, Any]] = None,
    sector_snapshot: Optional[dict[str, Any]] = None,
    holdings: Optional[list[dict[str, Any]]] = None,
    market_review_weekly: Optional[dict[str, Any]] = None,
    benchmark_excess_pct: Optional[float] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """3-5 macro headlines that measurably affected holdings."""
    sector_chg = _sector_change_map(sector_snapshot or {}, holdings or [])
    candidates = collect_macro_headline_candidates(
        macro_signals=macro_signals,
        sources=sources,
        portfolio=portfolio,
    )
    brief: list[dict[str, Any]] = []

    for row in candidates:
        if int(row.get("score") or 0) <= 0:
            continue
        sectors = str(row.get("sectors") or infer_affected_sectors(str(row.get("title") or ""), portfolio))
        sector_parts = [s.strip() for s in sectors.replace("、", ",").split(",") if s.strip()]
        matched_sector = ""
        matched_chg: Optional[float] = None
        for sp in sector_parts:
            if sp in sector_chg:
                matched_sector = sp
                matched_chg = sector_chg[sp]
                break
        if matched_chg is None:
            for sp in sector_parts:
                for label, chg in sector_chg.items():
                    if sp in label or label in sp:
                        matched_sector = label
                        matched_chg = chg
                        break
                if matched_chg is not None:
                    break
        if matched_chg is None:
            continue
        direction = "上涨" if matched_chg >= 0 else "下跌"
        impact = f"影响：导致 {matched_sector} {direction} {abs(matched_chg):.2f}%"
        brief.append(
            {
                "title": str(row.get("title") or "")[:96],
                "sectors": sectors,
                "impact": impact,
                "sector_change_pct": matched_chg,
                "score": int(row.get("score") or 0),
            }
        )
        if len(brief) >= limit:
            break

    mr = market_review_weekly or {}
    if len(brief) < 3 and mr.get("dominant_mainline"):
        mainline = str(mr.get("dominant_mainline"))
        best_sector = ""
        best_chg = 0.0
        for label, chg in sector_chg.items():
            if abs(chg) > abs(best_chg):
                best_sector = label
                best_chg = chg
        if best_sector and abs(best_chg) >= 0.3:
            direction = "上涨" if best_chg >= 0 else "下跌"
            brief.append(
                {
                    "title": f"本周主线 {mainline}，持仓板块 {best_sector} 跟随波动",
                    "sectors": best_sector,
                    "impact": f"影响：导致 {best_sector} {direction} {abs(best_chg):.2f}%",
                    "sector_change_pct": best_chg,
                    "score": 1,
                }
            )

    if len(brief) < 3 and benchmark_excess_pct is not None and abs(float(benchmark_excess_pct)) >= 0.5:
        direction = "跑赢" if float(benchmark_excess_pct) >= 0 else "跑输"
        brief.append(
            {
                "title": f"组合本周相对沪深300{direction}基准",
                "sectors": "组合",
                "impact": f"影响：超额收益 {float(benchmark_excess_pct):+.2f}%",
                "sector_change_pct": float(benchmark_excess_pct),
                "score": 1,
            }
        )

    brief.sort(key=lambda r: (-abs(float(r.get("sector_change_pct") or 0)), -int(r.get("score") or 0)))
    return brief[:limit]


def render_weekly_macro_brief_markdown(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["## 🌍 宏观要闻（持仓相关）", "- 本周暂无对持仓产生可量化影响的要闻", ""]
    lines = ["## 🌍 宏观要闻（持仓相关）", ""]
    for idx, row in enumerate(items[:5], start=1):
        title = str(row.get("title") or "").strip()
        impact = str(row.get("impact") or "")
        lines.append(f"{idx}. {title}")
        if impact:
            lines.append(f"   - **{impact}**")
    lines.append("")
    return lines


def summarize_week_prediction_verification(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    """Aggregate close-manifest forecast_review into weekly prediction stats."""
    stats: dict[str, dict[str, int]] = {k: {"hits": 0, "total": 0} for k in _PRED_TYPES}
    cases: list[dict[str, Any]] = []

    close_rows = [
        m
        for m in manifests
        if m.get("job") == "close"
        and week_start.isoformat() <= str(m.get("_run_date") or "")[:10] <= week_end.isoformat()
    ]
    for record in close_rows:
        ds = str(record.get("_run_date") or "")[:10]
        forecast = _manifest_close_forecast(record)
        if not forecast:
            continue
        for ev in forecast.get("symbol_evals") or []:
            if not isinstance(ev, dict):
                continue
            pred_dir = str(ev.get("predicted_direction") or "flat")
            actual = ev.get("actual_change_pct")
            hit = bool(ev.get("hit"))
            stats["标的涨跌"]["total"] += 1
            if hit:
                stats["标的涨跌"]["hits"] += 1
            is_trend = pred_dir in ("up", "down") and actual is not None
            if is_trend:
                same_sign = (pred_dir == "up" and float(actual) > 0.3) or (
                    pred_dir == "down" and float(actual) < -0.3
                )
                bucket = "趋势预测" if same_sign or not hit else "反转预测"
                stats[bucket]["total"] += 1
                if hit:
                    stats[bucket]["hits"] += 1
            cases.append(
                {
                    "date": ds,
                    "type": "标的涨跌",
                    "name": ev.get("name") or ev.get("code"),
                    "hit": hit,
                    "detail": (
                        f"预测 {pred_dir} 实际 {float(actual):+.2f}%"
                        if actual is not None
                        else str(ev.get("predicted_direction") or "")
                    ),
                    "score": abs(float(actual or 0)),
                }
            )
        if forecast.get("mss_hit") is not None:
            stats["MSS区间"]["total"] += 1
            if forecast.get("mss_hit"):
                stats["MSS区间"]["hits"] += 1
            cases.append(
                {
                    "date": ds,
                    "type": "MSS区间",
                    "name": "组合",
                    "hit": bool(forecast.get("mss_hit")),
                    "detail": f"MSS 预测 {forecast.get('mss_predicted')} vs 实际 {forecast.get('mss_actual')}",
                    "score": abs(float(forecast.get("mss_actual") or 0)),
                }
            )

    rows: list[dict[str, Any]] = []
    for pred_type in _PRED_TYPES:
        bucket = stats[pred_type]
        total = int(bucket["total"])
        if total <= 0:
            continue
        hits = int(bucket["hits"])
        rows.append(
            {
                "type": pred_type,
                "total": total,
                "hits": hits,
                "accuracy_pct": round(hits / total * 100.0, 1),
            }
        )

    hit_cases = [c for c in cases if c.get("hit")]
    miss_cases = [c for c in cases if not c.get("hit")]
    hit_cases.sort(key=lambda c: float(c.get("score") or 0), reverse=True)
    miss_cases.sort(key=lambda c: float(c.get("score") or 0), reverse=True)
    featured = []
    if hit_cases:
        featured.append(hit_cases[0])
    if miss_cases:
        featured.append(miss_cases[0])
    for c in hit_cases[1:2]:
        if c not in featured:
            featured.append(c)

    improvements: list[str] = []
    acc_map = {r["type"]: r["accuracy_pct"] for r in rows}
    trend_acc = acc_map.get("趋势预测")
    rev_acc = acc_map.get("反转预测")
    if trend_acc is not None and rev_acc is not None:
        improvements.append(
            f"趋势预测准确率 {trend_acc:.0f}%，反转预测 {rev_acc:.0f}%，"
            + ("需改进反转信号识别" if rev_acc < trend_acc else "反转识别尚可")
        )
    sym_acc = acc_map.get("标的涨跌")
    mss_acc = acc_map.get("MSS区间")
    if sym_acc is not None and mss_acc is not None and sym_acc - mss_acc >= 15:
        improvements.append(f"个股方向预测 {sym_acc:.0f}% 优于 MSS 区间 {mss_acc:.0f}%，可加强组合层校准")
    elif sym_acc is not None and sym_acc < 50:
        improvements.append(f"标的涨跌预测仅 {sym_acc:.0f}%，需收紧预测区间或降低仓位")

    return {
        "summary_rows": rows,
        "featured_cases": featured[:3],
        "improvements": improvements[:2],
        "days_reviewed": len({c.get("date") for c in cases}),
    }


def render_weekly_prediction_verify_markdown(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    structured = data.get("structured_review") or {}
    if structured.get("rows"):
        from agent_reach.daily_run.forecast_tracking import render_structured_week_verify_markdown

        lines.extend(render_structured_week_verify_markdown(structured))

    if not data or not data.get("summary_rows"):
        if lines:
            return lines
        return []
    if not lines:
        lines = ["## 🔮 本周预测验证", ""]
    else:
        lines.extend(["", "## 🔮 每日路径预测验证", ""])
    lines.extend(
        [
            "| 预测类型 | 总次数 | 命中次数 | 准确率 |",
            "|----------|--------|----------|--------|",
        ]
    )
    for row in data.get("summary_rows") or []:
        lines.append(
            f"| {row.get('type')} | {row.get('total')} | {row.get('hits')} | {float(row.get('accuracy_pct') or 0):.1f}% |"
        )
    daily_rows = data.get("daily_rows") or []
    if daily_rows:
        lines.extend(["", "**每日收盘卡片预测验证：**", ""])
        lines.extend(
            [
                "| 日期 | 标的命中 | MSS | 来源 |",
                "|------|----------|-----|------|",
            ]
        )
        for row in daily_rows:
            hits = row.get("symbol_hits")
            total = row.get("symbol_total")
            sym_s = f"{hits}/{total}" if total else "—"
            mss = row.get("mss_hit")
            mss_s = "✅" if mss is True else "❌" if mss is False else "—"
            lines.append(
                f"| {row.get('weekday')} {str(row.get('date') or '')[5:]} | {sym_s} "
                f"({float(row.get('accuracy_pct') or 0):.1f}%) | {mss_s} | {row.get('close_ref', '—')} |"
            )
    featured = data.get("featured_cases") or []
    if featured:
        lines.extend(["", "**典型案例：**"])
        for case in featured[:3]:
            mark = "✅" if case.get("hit") else "❌"
            lines.append(
                f"- {mark} {_weekday_label(str(case.get('date') or ''))} "
                f"{case.get('name')} · {case.get('detail')}"
            )
    improvements = data.get("improvements") or []
    if improvements:
        lines.extend(["", "**预测改进方向：**"])
        for note in improvements:
            lines.append(f"- {note}")
    monthly = data.get("monthly_optimization") or {}
    if monthly.get("rows") or monthly.get("recent_error_cases"):
        from agent_reach.daily_run.forecast_tracking import render_monthly_optimization_markdown

        lines.extend(render_monthly_optimization_markdown(monthly))
    lines.append("")
    return lines


def render_market_environment_markdown(
    *,
    macro_brief: list[dict[str, Any]],
    market_review_weekly: dict[str, Any],
    sector_snapshot: dict[str, Any],
    benchmark: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Single market environment card — macro + overview + holdings sectors once."""
    lines = ["## 🌐 市场环境", ""]
    lines.extend(render_weekly_macro_brief_markdown(macro_brief))

    if market_review_weekly:
        from agent_reach.daily_run.redfox_weekly import render_market_review_weekly_markdown

        mr_md = render_market_review_weekly_markdown(market_review_weekly)
        if mr_md:
            lines.extend(mr_md.splitlines())
            lines.append("")

    bench = benchmark or {}
    if bench.get("ok") and bench.get("return_pct") is not None:
        sign = "+" if float(bench["return_pct"]) >= 0 else ""
        lines.append(
            f"- **基准（{bench.get('name', '沪深300')} · 同期）：** {sign}{float(bench['return_pct']):.2f}%"
        )
        lines.append("")

    from agent_reach.daily_run.weekly_card_metrics import render_holdings_sector_markdown

    lines.extend(render_holdings_sector_markdown(sector_snapshot))
    return lines


def render_holdings_stock_logic_markdown(
    holdings: list[dict[str, Any]],
    *,
    holdings_as_of: str = "",
    benchmark_return_pct: Optional[float] = None,
) -> list[str]:
    """Stock cards: individual logic + relative performance only — no market/sector dump."""
    lines = ["## 📊 持股（个股逻辑）"]
    if holdings_as_of:
        lines.append(f"- **{holdings_as_of}**")
    if not holdings:
        lines.append("- 当前无持仓")
        lines.append("")
        return lines

    rows = sorted(holdings, key=lambda h: abs(float(h.get("week_chg") or 0)), reverse=True)
    for h in rows:
        name = h.get("name") or h.get("code")
        code = h.get("code")
        week_pct = h.get("week_chg_pct")
        rel_s = ""
        if week_pct is not None and benchmark_return_pct is not None:
            excess = float(week_pct) - float(benchmark_return_pct)
            rel_s = f" · 相对基准 {excess:+.2f}%"
        week_s = ""
        if h.get("week_chg") is not None:
            wc = float(h["week_chg"])
            pct_s = f"（{float(week_pct):+.2f}%）" if week_pct is not None else ""
            week_s = f"本周 {wc:+,.0f}元{pct_s}{rel_s}"
        elif week_pct is not None:
            week_s = f"本周 {float(week_pct):+.2f}%{rel_s}"
        logic_bits: list[str] = []
        if week_s:
            logic_bits.append(week_s)
        up = h.get("unrealized_pnl")
        if up is not None:
            logic_bits.append(f"成本浮盈 ¥{float(up):+,.0f}")
        if logic_bits:
            lines.append(f"- **{name}** ({code})：" + " · ".join(logic_bits))
        else:
            lines.append(f"- **{name}** ({code})")
    lines.append("")
    return lines


def build_weekly_pnl_brief(report: dict[str, Any]) -> list[str]:
    """Slim PnL narrative — no trade enumeration or daily replay."""
    lines: list[str] = []
    pnl = report.get("weekly_pnl")
    pct = report.get("weekly_pnl_pct")
    if pnl is None:
        return lines
    pnl_f = float(pnl)
    pct_f = float(pct) if pct is not None else 0.0
    if pnl_f > 0 and pct_f >= 1:
        verdict = f"本周组合盈利 **{pct_f:+.1f}%**（+¥{pnl_f:,.2f}）"
    elif pnl_f < 0 and pct_f <= -1:
        verdict = f"本周组合回撤 **{pct_f:.1f}%**（¥{pnl_f:,.2f}）"
    else:
        verdict = f"本周组合净值基本 **持平**（{pnl_f:+,.2f} 元，{pct_f:+.1f}%）"
    lines.append(f"- **总览：** {verdict}")
    return lines
