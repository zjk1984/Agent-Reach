# -*- coding: utf-8
"""Weekly-only analytics: 4-week trends, Brinson-lite attribution, param health, issues."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

_ISSUES_PATH = Path.home() / ".agent-reach" / "daily_run" / "weekly_issues.jsonl"

_DEFAULT_THRESHOLDS = {
    "max_single_stock_weight_pct": 25.0,
    "max_sector_weight_pct": 40.0,
    "max_weekly_turnover_pct": 50.0,
}


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _thresholds(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = ((settings or {}).get("weekly_report") or {}).get("strategy_health") or {}
    out = dict(_DEFAULT_THRESHOLDS)
    for key in out:
        val = _optional_float(cfg.get(key))
        if val is not None:
            out[key] = val
    return out


def _daily_totals_from_manifests(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from agent_reach.daily_run.weekly_report import _portfolio_total_from_manifest

    morning_totals: list[tuple[str, float]] = []
    close_totals: list[tuple[str, float]] = []
    for record in manifests:
        job = record.get("job")
        day = str(record.get("_run_date") or "")
        total = _portfolio_total_from_manifest(record)
        if total is None:
            continue
        if job == "morning":
            morning_totals.append((day, total))
        elif job == "close":
            close_totals.append((day, total))
    daily_totals: list[dict[str, Any]] = []
    for day, total in sorted(morning_totals, key=lambda x: x[0]):
        daily_totals.append({"date": day, "total": total, "job": "morning"})
    for day, total in sorted(close_totals, key=lambda x: x[0]):
        daily_totals.append({"date": day, "total": total, "job": "close"})
    return daily_totals


def _week_strategy_win_rate(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> Optional[float]:
    from agent_reach.daily_run.weekly_content_scope import summarize_week_prediction_verification

    data = summarize_week_prediction_verification(
        manifests,
        week_start=week_start,
        week_end=week_end,
    )
    rows = data.get("summary_rows") or []
    sym = next((r for r in rows if r.get("type") == "标的涨跌"), None)
    if sym and sym.get("total"):
        return float(sym.get("accuracy_pct"))
    return None


def build_four_week_trends(
    *,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
    current_return_pct: Optional[float] = None,
    current_risk: Optional[dict[str, Any]] = None,
    current_strategy_win_rate: Optional[float] = None,
) -> dict[str, Any]:
    """Rolling 4 trading weeks: return, win rate, max drawdown per week."""
    from agent_reach.daily_run.weekly_card_metrics import build_weekly_risk_metrics
    from agent_reach.daily_run.weekly_report import _load_week_manifests, trading_week_range
    from agent_reach.daily_run.weekly_signals import portfolio_return_between

    weeks: list[dict[str, Any]] = []
    for offset in range(3, -1, -1):
        ref = week_end - timedelta(days=7 * offset)
        ws, we = trading_week_range(ref)
        label = "本周" if offset == 0 else f"W-{offset}"
        ret = current_return_pct if offset == 0 and current_return_pct is not None else None
        if ret is None:
            ret = portfolio_return_between(ws, we, settings=settings)

        manifests = _load_week_manifests(ws, we)
        daily_totals = _daily_totals_from_manifests(manifests)
        risk = current_risk if offset == 0 and current_risk else build_weekly_risk_metrics(
            week_start=ws,
            week_end=we,
            daily_totals=daily_totals,
            settings=settings,
        )
        win_rate = (
            current_strategy_win_rate
            if offset == 0 and current_strategy_win_rate is not None
            else _week_strategy_win_rate(manifests, week_start=ws, week_end=we)
        )
        if win_rate is None:
            win_rate = risk.get("win_rate_pct")

        weeks.append(
            {
                "label": label,
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "return_pct": ret,
                "win_rate_pct": win_rate,
                "max_drawdown_pct": risk.get("max_drawdown_pct"),
            }
        )

    returns = [float(w["return_pct"]) for w in weeks if w.get("return_pct") is not None]
    win_rates = [float(w["win_rate_pct"]) for w in weeks if w.get("win_rate_pct") is not None]
    dds = [float(w["max_drawdown_pct"]) for w in weeks if w.get("max_drawdown_pct") is not None]

    assessment = "数据不足"
    if len(returns) >= 3:
        pos = sum(1 for r in returns if r > 0)
        neg = sum(1 for r in returns if r < 0)
        if pos >= 3:
            assessment = "策略持续有效（近4周多数盈利）"
        elif neg >= 3:
            assessment = "策略持续承压（近4周多数亏损）"
        elif returns[-1] > 0 and returns[-2] < 0:
            assessment = "本周反弹，前序波动较大"
        elif returns[-1] < 0 and returns[-2] > 0:
            assessment = "本周回调，或为偶然波动"
        else:
            assessment = "震荡期，需结合胜率与回撤综合判断"

    return {
        "weeks": weeks,
        "summary": {
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "avg_win_rate_pct": round(sum(win_rates) / len(win_rates), 1) if win_rates else None,
            "worst_drawdown_pct": max(dds) if dds else None,
            "assessment": assessment,
        },
    }


def build_brinson_attribution(
    *,
    holdings: list[dict[str, Any]],
    start_total: Optional[float],
    weekly_pnl_pct: Optional[float],
    sector_snapshot: dict[str, Any],
    prediction_verification: dict[str, Any],
    trade_pnl_detail: dict[str, Any],
    pnl_attribution: dict[str, Any],
) -> dict[str, Any]:
    """Simplified Brinson-style weekly attribution: sector beta, stock alpha, style mix."""
    base = float(start_total) if start_total and start_total > 0 else sum(
        float(h.get("market_value") or 0) for h in holdings
    )
    sector_rows = list((sector_snapshot or {}).get("sectors") or [])
    sector_avg: dict[str, float] = {}
    for row in sector_rows:
        sec = str(row.get("sector") or "其他")
        chg = _optional_float(row.get("avg_change_pct"))
        if chg is not None:
            sector_avg[sec] = chg

    stock_alpha_total = 0.0
    sector_beta_total = 0.0
    sector_contribs: list[dict[str, Any]] = []
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for h in holdings:
        sec = str(h.get("sector") or "其他")
        by_sector.setdefault(sec, []).append(h)

    for sec, rows in by_sector.items():
        sec_mv = sum(float(r.get("market_value") or 0) for r in rows)
        weight = sec_mv / base * 100.0 if base > 0 else 0.0
        sec_ret = sector_avg.get(sec)
        if sec_ret is None and rows:
            pcts = [_optional_float(r.get("week_chg_pct")) for r in rows]
            vals = [p for p in pcts if p is not None]
            sec_ret = sum(vals) / len(vals) if vals else 0.0
        sec_ret = float(sec_ret or 0)
        beta_contrib = round(weight * sec_ret / 100.0, 2)
        sector_beta_total += beta_contrib

        alpha = 0.0
        for r in rows:
            mv = float(r.get("market_value") or 0)
            w = mv / base if base > 0 else 0.0
            stock_pct = _optional_float(r.get("week_chg_pct")) or 0.0
            alpha += w * (stock_pct - sec_ret)
        alpha = round(alpha, 2)
        stock_alpha_total += alpha
        sector_contribs.append(
            {
                "sector": sec,
                "weight_pct": round(weight, 1),
                "sector_return_pct": round(sec_ret, 2),
                "beta_contribution_pct": beta_contrib,
                "alpha_contribution_pct": alpha,
            }
        )
    sector_contribs.sort(key=lambda r: abs(float(r.get("beta_contribution_pct") or 0)), reverse=True)

    summary_rows = prediction_verification.get("summary_rows") or []
    trend = next((r for r in summary_rows if r.get("type") == "趋势预测"), None)
    reversal = next((r for r in summary_rows if r.get("type") == "反转预测"), None)
    style_rows: list[dict[str, Any]] = []
    for label, row in (("趋势跟踪", trend), ("反转策略", reversal)):
        if row and row.get("total"):
            style_rows.append(
                {
                    "style": label,
                    "total": row.get("total"),
                    "hits": row.get("hits"),
                    "accuracy_pct": row.get("accuracy_pct"),
                }
            )

    sells = trade_pnl_detail.get("sells") or []
    sell_wins = sum(1 for s in sells if float(s.get("realized_pnl") or 0) > 0)
    sell_total = len(sells)

    held = _optional_float(pnl_attribution.get("held_week_chg"))
    realized = _optional_float(pnl_attribution.get("realized_pnl"))

    return {
        "weekly_return_pct": weekly_pnl_pct,
        "sector_beta_pct": round(sector_beta_total, 2),
        "stock_alpha_pct": round(stock_alpha_total, 2),
        "sector_rows": sector_contribs[:6],
        "style_rows": style_rows,
        "sell_win_rate_pct": round(sell_wins / sell_total * 100.0, 1) if sell_total else None,
        "sell_count": sell_total,
        "held_pnl": held,
        "realized_pnl": realized,
        "interpretation": _attribution_interpretation(
            weekly_pnl_pct=weekly_pnl_pct,
            sector_beta=sector_beta_total,
            stock_alpha=stock_alpha_total,
            style_rows=style_rows,
        ),
    }


def _attribution_interpretation(
    *,
    weekly_pnl_pct: Optional[float],
    sector_beta: float,
    stock_alpha: float,
    style_rows: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if weekly_pnl_pct is not None:
        if abs(stock_alpha) >= abs(sector_beta):
            parts.append(
                "本周收益主要来自选股能力（个股 alpha）"
                if stock_alpha >= 0
                else "本周亏损主要来自个股选择（alpha 拖累）"
            )
        else:
            parts.append(
                "本周收益跟随板块 beta"
                if sector_beta >= 0
                else "本周亏损主要来自板块 beta 下行"
            )
    if style_rows:
        best = max(style_rows, key=lambda r: float(r.get("accuracy_pct") or 0))
        if best.get("accuracy_pct") is not None:
            parts.append(f"{best['style']}更有效（准确率 {float(best['accuracy_pct']):.0f}%）")
    return "；".join(parts) if parts else "归因数据不足，需更多收盘预测与持仓明细"


def build_strategy_parameter_health(
    *,
    holdings: list[dict[str, Any]],
    sector_snapshot: dict[str, Any],
    trade_log: list[dict[str, Any]],
    start_total: Optional[float],
    end_total: Optional[float],
    strategy_validation: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Check concentration, sector diversification, turnover vs thresholds."""
    thr = _thresholds(settings)
    checks: list[dict[str, Any]] = []
    base = float(end_total or start_total or 0)

    max_weight = 0.0
    max_name = ""
    for h in holdings:
        mv = float(h.get("market_value") or 0)
        weight = mv / base * 100.0 if base > 0 else 0.0
        if weight > max_weight:
            max_weight = weight
            max_name = str(h.get("name") or h.get("code") or "")
    checks.append(
        _health_check(
            name="单股集中度",
            value=max_weight,
            threshold=thr["max_single_stock_weight_pct"],
            unit="%",
            detail=max_name or "—",
            higher_is_bad=True,
        )
    )

    max_sector = 0.0
    max_sector_name = ""
    for row in (sector_snapshot or {}).get("sectors") or []:
        w = _optional_float(row.get("weight_pct")) or 0.0
        if w > max_sector:
            max_sector = w
            max_sector_name = str(row.get("sector") or "")
    checks.append(
        _health_check(
            name="行业集中度",
            value=max_sector,
            threshold=thr["max_sector_weight_pct"],
            unit="%",
            detail=max_sector_name or "—",
            higher_is_bad=True,
        )
    )

    trade_amount = sum(abs(_optional_float(t.get("amount")) or 0.0) for t in trade_log)
    denom = base if base > 0 else 1.0
    turnover = round(trade_amount / denom * 100.0, 1)
    checks.append(
        _health_check(
            name="周换手率",
            value=turnover,
            threshold=thr["max_weekly_turnover_pct"],
            unit="%",
            detail=f"成交额 ¥{trade_amount:,.0f}",
            higher_is_bad=True,
        )
    )

    win_rate = _optional_float(strategy_validation.get("win_rate_pct"))
    if win_rate is not None:
        checks.append(
            {
                "name": "策略信号胜率",
                "value": win_rate,
                "threshold": 50.0,
                "unit": "%",
                "ok": win_rate >= 50.0,
                "severity": "warn" if win_rate < 50.0 else "ok",
                "detail": f"触发 {strategy_validation.get('signal_count', 0)} 个信号",
                "message": (
                    f"策略胜率 {win_rate:.1f}% 低于 50%"
                    if win_rate < 50.0
                    else f"策略胜率 {win_rate:.1f}% 正常"
                ),
            }
        )

    failed = [c for c in checks if not c.get("ok")]
    status = "ok"
    if any(c.get("severity") == "alert" for c in failed):
        status = "alert"
    elif failed:
        status = "warn"

    return {
        "status": status,
        "checks": checks,
        "thresholds": thr,
        "warnings": [c["message"] for c in failed],
    }


def _health_check(
    *,
    name: str,
    value: float,
    threshold: float,
    unit: str,
    detail: str,
    higher_is_bad: bool,
) -> dict[str, Any]:
    ok = value <= threshold if higher_is_bad else value >= threshold
    severity = "ok"
    if not ok:
        severity = "alert" if value > threshold * 1.2 else "warn"
    msg = f"{name} {value:.1f}{unit}（{detail}）"
    if not ok:
        msg += f" 超出阈值 {threshold:.0f}{unit}"
    else:
        msg += " 正常"
    return {
        "name": name,
        "value": round(value, 2),
        "threshold": threshold,
        "unit": unit,
        "ok": ok,
        "severity": severity,
        "detail": detail,
        "message": msg,
    }


def _issue_id(title: str, category: str = "") -> str:
    raw = f"{category}|{title}".strip().lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip())


def _titles_match(a: str, b: str) -> bool:
    left, right = _normalize_title(a), _normalize_title(b)
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True
    prefix = min(len(left), len(right), 12)
    return prefix >= 8 and left[:prefix] == right[:prefix]


def _match_prior_issue(
    item: dict[str, Any],
    prior_open: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    direct = prior_open.get(str(item.get("id") or ""))
    if direct:
        return direct
    for pitem in prior_open.values():
        if str(pitem.get("category") or "") != str(item.get("category") or ""):
            continue
        if _titles_match(str(item.get("title") or ""), str(pitem.get("title") or "")):
            return pitem
    return None


def load_prior_weekly_issues(before_week_end: date) -> Optional[dict[str, Any]]:
    """Most recent issues snapshot strictly before `before_week_end`."""
    if not _ISSUES_PATH.is_file():
        return None
    best: Optional[dict[str, Any]] = None
    best_end = ""
    for line in _ISSUES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        we = str(row.get("week_end") or "")
        if not we or we >= before_week_end.isoformat():
            continue
        if we > best_end:
            best_end = we
            best = row
    return best


def build_pending_issues(
    *,
    week_end: date,
    process_improvements: list[dict[str, Any]],
    strategy_health: dict[str, Any],
    strategy_validation: dict[str, Any],
    prior_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Open issues for this week + week-over-week resolution tracking."""
    current: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        title: str,
        *,
        detail: str = "",
        priority: str = "medium",
        category: str = "workflow",
        source: str = "process_improvement",
        action: str = "",
    ) -> None:
        title = _normalize_title(title)
        if not title:
            return
        iid = _issue_id(title, category)
        if iid in seen:
            return
        seen.add(iid)
        current.append(
            {
                "id": iid,
                "title": title,
                "detail": detail,
                "priority": priority,
                "category": category,
                "source": source,
                "action": action,
                "status": "open",
            }
        )

    for item in process_improvements:
        _add(
            str(item.get("title") or ""),
            detail=str(item.get("detail") or ""),
            priority=str(item.get("priority") or "medium"),
            category=str(item.get("category") or "workflow"),
            source="process_improvement",
            action=str(item.get("action") or ""),
        )

    for msg in strategy_health.get("warnings") or []:
        _add(msg, detail="策略参数健康度检查", priority="high", category="portfolio", source="strategy_health")

    for sug in strategy_validation.get("suggestions") or []:
        text = str(sug or "")
        if "连续 2 周" in text or "低于 50%" in text or "暂停" in text:
            _add(text, detail="策略验证", priority="high", category="skill", source="strategy_validation")

    prior_issues = list((prior_snapshot or {}).get("issues") or [])
    prior_open = {str(i.get("id")): i for i in prior_issues if i.get("status") != "resolved"}
    current_ids = {i["id"] for i in current}
    matched_prior_ids: set[str] = set()

    resolved: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    new_items: list[dict[str, Any]] = []
    for item in current:
        prior_item = _match_prior_issue(item, prior_open)
        if prior_item:
            matched_prior_ids.add(str(prior_item.get("id") or item["id"]))
            carried.append(
                {
                    **item,
                    "status": "carried",
                    "since_week_end": prior_snapshot.get("week_end") if prior_snapshot else None,
                }
            )
        else:
            new_items.append({**item, "status": "new"})

    for iid, item in prior_open.items():
        if iid in matched_prior_ids:
            continue
        if any(_titles_match(str(item.get("title") or ""), str(c.get("title") or "")) for c in current):
            continue
        resolved.append({**item, "status": "resolved", "resolved_week_end": week_end.isoformat()})

    return {
        "week_end": week_end.isoformat(),
        "open": current,
        "new_this_week": new_items,
        "carried_over": carried,
        "resolved_this_week": resolved,
        "prior_week_end": (prior_snapshot or {}).get("week_end"),
        "counts": {
            "open": len(current),
            "new": len(new_items),
            "carried": len(carried),
            "resolved": len(resolved),
        },
    }


def save_weekly_issues(snapshot: dict[str, Any]) -> Path:
    _ISSUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    week_end = str(snapshot.get("week_end") or "")
    existing: list[str] = []
    if _ISSUES_PATH.is_file():
        for line in _ISSUES_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                existing.append(line)
                continue
            if str(row.get("week_end") or "") != week_end:
                existing.append(line)
    payload = {
        "week_end": week_end,
        "issues": snapshot.get("open") or [],
        "resolved": snapshot.get("resolved_this_week") or [],
        "counts": snapshot.get("counts") or {},
    }
    existing.append(json.dumps(payload, ensure_ascii=False))
    _ISSUES_PATH.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return _ISSUES_PATH


def render_four_week_trends_markdown(data: dict[str, Any]) -> list[str]:
    weeks = data.get("weeks") or []
    if not weeks:
        return []
    lines = [
        "## 📉 近4周趋势",
        "",
        "| 周期 | 收益率 | 胜率 | 最大回撤 |",
        "|------|--------|------|----------|",
    ]
    for row in weeks:
        ret = row.get("return_pct")
        win = row.get("win_rate_pct")
        dd = row.get("max_drawdown_pct")
        ret_s = f"{float(ret):+.1f}%" if ret is not None else "—"
        win_s = f"{float(win):.1f}%" if win is not None else "—"
        dd_s = f"{float(dd):.2f}%" if dd is not None else "—"
        lines.append(f"| {row.get('label')} | {ret_s} | {win_s} | {dd_s} |")
    summary = data.get("summary") or {}
    if summary.get("assessment"):
        lines.append("")
        lines.append(f"- **趋势判断：** {summary['assessment']}")
    if summary.get("avg_return_pct") is not None:
        lines.append(f"- **4周均值：** 收益 {float(summary['avg_return_pct']):+.1f}%")
    lines.append("")
    return lines


def render_brinson_attribution_markdown(data: dict[str, Any]) -> list[str]:
    if not data:
        return []
    lines = ["## 🧮 归因分析", ""]
    beta = data.get("sector_beta_pct")
    alpha = data.get("stock_alpha_pct")
    if beta is not None or alpha is not None:
        lines.append(
            f"- **板块 beta：** {_fmt_signed_pct(beta)} · **个股 alpha：** {_fmt_signed_pct(alpha)}"
        )
    if data.get("interpretation"):
        lines.append(f"- **解读：** {data['interpretation']}")

    sector_rows = data.get("sector_rows") or []
    if sector_rows:
        lines.extend(["", "| 行业 | 权重 | 行业涨跌 | beta贡献 | alpha贡献 |", "|------|------|---------|---------|----------|"])
        for row in sector_rows[:5]:
            lines.append(
                f"| {row.get('sector')} | {float(row.get('weight_pct') or 0):.0f}% "
                f"| {_fmt_signed_pct(row.get('sector_return_pct'))} "
                f"| {_fmt_signed_pct(row.get('beta_contribution_pct'))} "
                f"| {_fmt_signed_pct(row.get('alpha_contribution_pct'))} |"
            )

    style_rows = data.get("style_rows") or []
    if style_rows:
        lines.extend(["", "**策略风格验证：**"])
        for row in style_rows:
            acc = row.get("accuracy_pct")
            acc_s = f"{float(acc):.0f}%" if acc is not None else "—"
            lines.append(
                f"- {row.get('style')}：{row.get('hits')}/{row.get('total')} 命中（{acc_s}）"
            )
    lines.append("")
    return lines


def render_strategy_health_markdown(data: dict[str, Any]) -> list[str]:
    if not data or not data.get("checks"):
        return []
    status = str(data.get("status") or "ok")
    icon = "✅" if status == "ok" else "⚠️" if status == "warn" else "🔴"
    lines = [f"## {icon} 策略参数健康度", ""]
    for check in data.get("checks") or []:
        mark = "✅" if check.get("ok") else "⚠️" if check.get("severity") == "warn" else "🔴"
        lines.append(f"- {mark} {check.get('message')}")
    lines.append("")
    return lines


def render_pending_issues_markdown(data: dict[str, Any]) -> list[str]:
    if not data:
        return []
    lines = ["## 📌 待解决问题", ""]
    resolved = data.get("resolved_this_week") or []
    if resolved:
        lines.append("**上周已解决：**")
        for item in resolved[:5]:
            lines.append(f"- ✅ {item.get('title')}")
        lines.append("")

    carried = data.get("carried_over") or []
    if carried:
        lines.append("**持续跟踪：**")
        for item in carried[:6]:
            pri = str(item.get("priority") or "")
            mark = "🔴" if pri == "high" else "🟡" if pri == "medium" else "🟢"
            lines.append(f"- {mark} {item.get('title')}")
            if item.get("action"):
                lines.append(f"  - _行动：{item['action']}_")
        lines.append("")

    new_items = data.get("new_this_week") or []
    if new_items:
        lines.append("**本周新增：**")
        for item in new_items[:6]:
            lines.append(f"- 🆕 {item.get('title')}")
        lines.append("")

    if not resolved and not carried and not new_items:
        open_items = data.get("open") or []
        if not open_items:
            lines.append("- 本周暂无待办问题 🎉")
        else:
            for item in open_items[:8]:
                lines.append(f"- {item.get('title')}")
        lines.append("")

    counts = data.get("counts") or {}
    if any(counts.get(k) for k in ("open", "resolved", "new", "carried")):
        lines.append(
            f"- _开放 {counts.get('open', 0)} · 新增 {counts.get('new', 0)} · "
            f"延续 {counts.get('carried', 0)} · 已解决 {counts.get('resolved', 0)}_"
        )
    lines.append("")
    return lines


def _fmt_signed_pct(value: Any) -> str:
    v = _optional_float(value)
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"
