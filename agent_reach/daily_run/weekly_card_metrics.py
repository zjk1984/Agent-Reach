# -*- coding: utf-8
"""Weekly card metrics — return, risk, trades, sectors for Saturday report cards."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

_SH_TZ = ZoneInfo("Asia/Shanghai")
_DEFAULT_BENCHMARK_KEY = "sh000300"
_DEFAULT_BENCHMARK_NAME = "沪深300"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _index_info_on_day(review_day: date, index_key: str = _DEFAULT_BENCHMARK_KEY) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.market_review import load_market_review

    review = load_market_review(review_day.isoformat())
    if not review:
        return None
    indices = review.get("indices") or {}
    info = indices.get(index_key)
    return dict(info) if isinstance(info, dict) else None


def _trading_days_between(start: date, end: date, *, settings: Optional[dict[str, Any]] = None) -> list[date]:
    from agent_reach.daily_run.trade_calendar import is_trading_day

    days: list[date] = []
    cursor = start
    cfg = settings or {}
    while cursor <= end:
        ok, _ = is_trading_day(cursor, settings=cfg)
        if ok:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def fetch_benchmark_weekly_return(
    week_start: date,
    week_end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
    index_key: str = _DEFAULT_BENCHMARK_KEY,
    index_name: str = _DEFAULT_BENCHMARK_NAME,
) -> dict[str, Any]:
    """Same-period benchmark return using saved market_review index snapshots."""
    cfg = (settings or {}).get("weekly_report") or {}
    index_key = str(cfg.get("benchmark_index_key") or index_key)
    index_name = str(cfg.get("benchmark_index_name") or index_name)

    start_info = _index_info_on_day(week_start, index_key)
    end_info = _index_info_on_day(week_end, index_key)

    start_px: Optional[float] = None
    end_px: Optional[float] = None
    if start_info:
        start_px = _optional_float(start_info.get("open")) or _optional_float(start_info.get("prev_close"))
    if end_info:
        end_px = _optional_float(end_info.get("price")) or _optional_float(end_info.get("prev_close"))

    if start_px is None or end_px is None or start_px <= 0:
        return {
            "name": index_name,
            "index_key": index_key,
            "return_pct": None,
            "start_price": start_px,
            "end_price": end_px,
            "period": f"{week_start.isoformat()} ~ {week_end.isoformat()}",
            "source": "market_review",
            "ok": False,
            "error": "⚠️ 数据获取失败（缺少同期指数收盘/开盘）",
        }

    ret_pct = round((end_px - start_px) / start_px * 100.0, 2)
    return {
        "name": index_name,
        "index_key": index_key,
        "return_pct": ret_pct,
        "start_price": round(start_px, 2),
        "end_price": round(end_px, 2),
        "period": f"{week_start.isoformat()} ~ {week_end.isoformat()}",
        "source": "market_review",
        "ok": True,
    }


def build_weekly_return_metrics(
    *,
    week_start: date,
    week_end: date,
    start_total: Optional[float],
    end_total: Optional[float],
    weekly_pnl: Optional[float],
    weekly_pnl_pct: Optional[float],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    absolute_pct = weekly_pnl_pct
    if absolute_pct is None and start_total and end_total and start_total > 0:
        absolute_pct = round((float(end_total) - float(start_total)) / float(start_total) * 100.0, 2)

    benchmark = fetch_benchmark_weekly_return(week_start, week_end, settings=settings)
    excess: Optional[float] = None
    if absolute_pct is not None and benchmark.get("return_pct") is not None:
        excess = round(float(absolute_pct) - float(benchmark["return_pct"]), 2)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "start_total": start_total,
        "end_total": end_total,
        "absolute_return_amount": weekly_pnl,
        "absolute_return_pct": absolute_pct,
        "costs_included": True,
        "costs_note": "基于实际账户净值，已含 ledger 记录的买卖佣金",
        "nav_source": "daily-run 收盘 manifest 实际净值",
        "benchmark": benchmark,
        "excess_return_pct": excess,
    }


def flatten_ledger_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten ledger entries to one row per executed action."""
    rows: list[dict[str, Any]] = []
    for entry in trades:
        date_s = str(entry.get("at") or entry.get("date") or "")[:10]
        for action in entry.get("actions") or []:
            if not isinstance(action, dict):
                continue
            side = str(action.get("side") or "")
            if side not in ("buy", "sell"):
                continue
            rows.append(
                {
                    "date": date_s,
                    "code": str(action.get("code") or ""),
                    "name": str(action.get("name") or action.get("code") or ""),
                    "side": "买" if side == "buy" else "卖",
                    "side_raw": side,
                    "price": _optional_float(action.get("price")),
                    "shares": int(action.get("shares") or 0),
                    "amount": round(_optional_float(action.get("amount")) or 0.0, 2),
                    "commission": round(_optional_float(action.get("commission")) or 0.0, 2),
                    "source": "ledger",
                }
            )
    rows.sort(key=lambda r: (r.get("date") or "", r.get("code") or ""))
    return rows


def reconcile_week_trades(
    *,
    trades: list[dict[str, Any]],
    start_cash: Optional[float],
    end_cash: Optional[float],
    start_stock_mv: Optional[float],
    end_stock_mv: Optional[float],
) -> dict[str, Any]:
    flat = flatten_ledger_trades(trades)
    buy_total = sum(r["amount"] + r["commission"] for r in flat if r["side_raw"] == "buy")
    sell_total = sum(r["amount"] - r["commission"] for r in flat if r["side_raw"] == "sell")
    buy_amount = sum(r["amount"] for r in flat if r["side_raw"] == "buy")
    sell_amount = sum(r["amount"] for r in flat if r["side_raw"] == "sell")
    cash_delta = None
    stock_delta = None
    if start_cash is not None and end_cash is not None:
        cash_delta = round(float(end_cash) - float(start_cash), 2)
    if start_stock_mv is not None and end_stock_mv is not None:
        stock_delta = round(float(end_stock_mv) - float(start_stock_mv), 2)

    cash_lhs: Optional[float] = None
    cash_rhs: Optional[float] = None
    cash_diff: Optional[float] = None
    stock_lhs: Optional[float] = None
    stock_rhs: Optional[float] = None
    stock_diff: Optional[float] = None
    ok = True
    tol = 50.0

    if cash_delta is not None:
        cash_lhs = round(buy_total - sell_total, 2)
        cash_rhs = round(-cash_delta, 2)
        cash_diff = round(cash_lhs - cash_rhs, 2)
        ok = ok and abs(cash_diff) <= max(tol, abs(cash_rhs) * 0.02 + 1.0)

    if stock_delta is not None:
        stock_lhs = round(buy_amount - sell_amount, 2)
        stock_rhs = stock_delta
        stock_diff = round(stock_lhs - stock_rhs, 2)
        ok = ok and abs(stock_diff) <= max(tol, abs(stock_rhs) * 0.02 + 1.0)

    return {
        "buy_total": round(buy_total, 2),
        "sell_total": round(sell_total, 2),
        "buy_amount": round(buy_amount, 2),
        "sell_amount": round(sell_amount, 2),
        "cash_delta": cash_delta,
        "stock_mv_delta": stock_delta,
        "identity_lhs": cash_lhs,
        "identity_rhs": cash_rhs,
        "identity_diff": cash_diff,
        "stock_identity_lhs": stock_lhs,
        "stock_identity_rhs": stock_rhs,
        "stock_identity_diff": stock_diff,
        "ok": ok,
        "trade_count": len(flat),
    }


def _daily_close_totals(daily_totals: list[dict[str, Any]]) -> list[tuple[str, float]]:
    rows = [
        (str(r.get("date") or ""), float(r["total"]))
        for r in daily_totals
        if r.get("job") == "close" and r.get("total") is not None and str(r.get("date") or "")
    ]
    rows.sort(key=lambda x: x[0])
    deduped: list[tuple[str, float]] = []
    seen: set[str] = set()
    for ds, total in rows:
        if ds in seen:
            continue
        seen.add(ds)
        deduped.append((ds, total))
    return deduped


def _daily_returns(closes: list[tuple[str, float]]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1][1]
        cur = closes[i][1]
        if prev > 0:
            out.append((cur - prev) / prev)
    return out


def _max_drawdown(closes: list[tuple[str, float]]) -> Optional[float]:
    if len(closes) < 2:
        return None
    peak = closes[0][1]
    max_dd = 0.0
    for _, px in closes:
        if px > peak:
            peak = px
        if peak > 0:
            dd = (peak - px) / peak
            max_dd = max(max_dd, dd)
    return round(max_dd * 100.0, 2)


def _benchmark_daily_returns(
    week_start: date,
    week_end: date,
) -> list[float]:
    days = _trading_days_between(week_start, week_end)
    closes: list[float] = []
    for d in days:
        info = _index_info_on_day(d, _DEFAULT_BENCHMARK_KEY)
        px = _optional_float((info or {}).get("price")) if info else None
        if px is not None and px > 0:
            closes.append(px)
    if len(closes) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return out


def build_weekly_risk_metrics(
    *,
    week_start: date,
    week_end: date,
    daily_totals: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    closes = _daily_close_totals(daily_totals)
    trading_days = _trading_days_between(week_start, week_end, settings=settings)
    window_n = len(trading_days) or len(closes)
    daily_rets = _daily_returns(closes)

    max_dd = _max_drawdown(closes)
    vol = statistics.pstdev(daily_rets) * math.sqrt(252) * 100.0 if len(daily_rets) >= 2 else None
    win_days = sum(1 for r in daily_rets if r > 0)
    win_rate = round(win_days / len(daily_rets) * 100.0, 1) if daily_rets else None

    bench_rets = _benchmark_daily_returns(week_start, week_end)
    bench_dd = None
    bench_vol = None
    bench_win = None
    if bench_rets:
        bench_closes: list[tuple[str, float]] = []
        for d in _trading_days_between(week_start, week_end, settings=settings):
            info = _index_info_on_day(d, _DEFAULT_BENCHMARK_KEY)
            px = _optional_float((info or {}).get("price")) if info else None
            if px is not None:
                bench_closes.append((d.isoformat(), px))
        bench_dd = _max_drawdown(bench_closes)
        bench_vol = (
            statistics.pstdev(bench_rets) * math.sqrt(252) * 100.0 if len(bench_rets) >= 2 else None
        )
        bench_win = round(sum(1 for r in bench_rets if r > 0) / len(bench_rets) * 100.0, 1)

    return {
        "window_label": f"本周 {window_n} 个交易日",
        "trading_days": window_n,
        "max_drawdown_pct": max_dd,
        "volatility_ann_pct": round(vol, 2) if vol is not None else None,
        "win_rate_pct": win_rate,
        "benchmark": {
            "name": _DEFAULT_BENCHMARK_NAME,
            "max_drawdown_pct": bench_dd,
            "volatility_ann_pct": round(bench_vol, 2) if bench_vol is not None else None,
            "win_rate_pct": bench_win,
            "ok": bench_rets != [],
        },
    }


def build_holdings_sector_snapshot(
    holdings: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Sector rows for holdings only, with live fetch + cutoff label."""
    _ = settings
    now = datetime.now(_SH_TZ)
    as_of_label = now.strftime("截至 %Y-%m-%d %H:%M")
    sectors: dict[str, dict[str, Any]] = {}

    for row in holdings:
        sector = str(row.get("sector") or "未分类").strip() or "未分类"
        bucket = sectors.setdefault(
            sector,
            {
                "sector": sector,
                "symbols": [],
                "avg_change_pct": None,
                "weight_pct": 0.0,
            },
        )
        chg = _optional_float(
            row.get("week_chg_pct") if row.get("week_chg_pct") is not None else row.get("change_pct")
        )
        bucket["symbols"].append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "change_pct": chg,
            }
        )

    fetch_ok = True
    fetch_error = ""
    live: dict[str, Any] = {}
    try:
        from agent_reach.daily_run.eastmoney_market import fetch_indices

        live = fetch_indices(timeout=12.0)
        if not live:
            fetch_ok = False
            fetch_error = "⚠️ 数据获取失败"
    except Exception:
        live = {}
        fetch_ok = False
        fetch_error = "⚠️ 数据获取失败"

    rows_out: list[dict[str, Any]] = []
    for sector, bucket in sectors.items():
        changes = [s["change_pct"] for s in bucket["symbols"] if s.get("change_pct") is not None]
        avg = round(sum(changes) / len(changes), 2) if changes else None
        rows_out.append(
            {
                "sector": sector,
                "avg_change_pct": avg,
                "symbols": bucket["symbols"][:4],
                "symbol_count": len(bucket["symbols"]),
            }
        )
    rows_out.sort(key=lambda r: abs(float(r.get("avg_change_pct") or 0)), reverse=True)

    return {
        "as_of": now.isoformat(),
        "as_of_label": as_of_label,
        "fetch_ok": fetch_ok,
        "fetch_error": fetch_error if not fetch_ok else "",
        "live_indices_ok": bool(live),
        "sectors": rows_out,
    }


def render_weekly_return_markdown(metrics: dict[str, Any]) -> list[str]:
    if not metrics:
        return []
    lines = ["## 💰 本周收益（实际净值）"]
    start = metrics.get("start_total")
    end = metrics.get("end_total")
    abs_pct = metrics.get("absolute_return_pct")
    abs_amt = metrics.get("absolute_return_amount")
    if start is not None and end is not None:
        lines.append(f"- **周初净值：** ¥{float(start):,.2f} → **周末净值：** ¥{float(end):,.2f}")
    if abs_pct is not None:
        sign = "+" if float(abs_pct) >= 0 else ""
        amt_s = ""
        if abs_amt is not None:
            amt_s = f"（{('+' if float(abs_amt) >= 0 else '')}¥{float(abs_amt):,.2f}）"
        lines.append(f"- **周度收益率：** {sign}{float(abs_pct):.2f}%{amt_s}")
    if metrics.get("costs_note"):
        lines.append(f"- _{metrics['costs_note']}_")

    bench = metrics.get("benchmark") or {}
    if bench.get("ok") and bench.get("return_pct") is not None:
        bsign = "+" if float(bench["return_pct"]) >= 0 else ""
        lines.append(
            f"- **基准（{bench.get('name')} · 同期）：** {bsign}{float(bench['return_pct']):.2f}% "
            f"（{bench.get('start_price')} → {bench.get('end_price')}）"
        )
    elif bench.get("error"):
        lines.append(f"- **基准对比：** {bench['error']}")

    excess = metrics.get("excess_return_pct")
    if excess is not None:
        esign = "+" if float(excess) >= 0 else ""
        lines.append(f"- **超额收益（vs 基准）：** {esign}{float(excess):.2f}%")
    lines.append("")
    return lines


def render_weekly_risk_markdown(risk: dict[str, Any]) -> list[str]:
    if not risk:
        return []
    lines = ["## ⚠️ 本周风险指标", f"- **计算窗口：** {risk.get('window_label', '本周')}"]
    dd = risk.get("max_drawdown_pct")
    vol = risk.get("volatility_ann_pct")
    win = risk.get("win_rate_pct")
    if dd is not None:
        lines.append(f"- **最大回撤：** {float(dd):.2f}%")
    if vol is not None:
        lines.append(f"- **波动率（日收益年化）：** {float(vol):.2f}%")
    if win is not None:
        lines.append(f"- **胜率（盈利交易日/总交易日）：** {float(win):.1f}%")

    bench = risk.get("benchmark") or {}
    if bench.get("ok"):
        parts: list[str] = []
        if bench.get("max_drawdown_pct") is not None:
            parts.append(f"回撤 {float(bench['max_drawdown_pct']):.2f}%")
        if bench.get("volatility_ann_pct") is not None:
            parts.append(f"波动 {float(bench['volatility_ann_pct']):.2f}%")
        if bench.get("win_rate_pct") is not None:
            parts.append(f"胜率 {float(bench['win_rate_pct']):.1f}%")
        if parts:
            lines.append(f"- **基准（{bench.get('name', _DEFAULT_BENCHMARK_NAME)}）：** " + " · ".join(parts))
    else:
        lines.append("- **基准风险对比：** ⚠️ 数据获取失败")
    panel = risk.get("risk_panel") or {}
    if panel and not panel.get("skipped"):
        try:
            from agent_reach.daily_run.risk_panel import render_risk_panel_markdown

            extra = render_risk_panel_markdown(panel)
            if extra:
                lines.extend(extra.splitlines())
        except Exception:
            pass
    lines.append("")
    return lines


def render_weekly_trade_log_markdown(
    trade_log: list[dict[str, Any]],
    reconciliation: dict[str, Any],
) -> list[str]:
    lines = ["## 📝 本周交易日志", "- _来源：trade ledger 实际成交（非模型计划）_"]
    if not trade_log:
        lines.append("- 本周无 ledger 成交记录")
    else:
        lines.extend(
            [
                "",
                "| 日期 | 股票 | 方向 | 价格 | 数量 | 金额 | 手续费 |",
                "|------|------|------|------|------|------|--------|",
            ]
        )
        for row in trade_log[:20]:
            price_s = f"{float(row['price']):.2f}" if row.get("price") is not None else "—"
            lines.append(
                f"| {row.get('date')} | {row.get('name')} | {row.get('side')} | {price_s} "
                f"| {row.get('shares')} | ¥{float(row.get('amount') or 0):,.0f} "
                f"| ¥{float(row.get('commission') or 0):,.2f} |"
            )
    if reconciliation:
        mark = "✅" if reconciliation.get("ok") else "❌"
        lines.append("")
        lines.append(
            f"- **流水校验 {mark}（现金）：** 买入 ¥{float(reconciliation.get('buy_total') or 0):,.0f} "
            f"- 卖出 ¥{float(reconciliation.get('sell_total') or 0):,.0f} "
            f"= 现金流出 ¥{float(reconciliation.get('identity_rhs') or 0):,.0f} "
            f"（现金变动 ¥{float(reconciliation.get('cash_delta') or 0):+,.0f}）"
        )
        if reconciliation.get("stock_identity_lhs") is not None:
            lines.append(
                f"- **流水校验 {mark}（持仓）：** 买入金额 ¥{float(reconciliation.get('buy_amount') or 0):,.0f} "
                f"- 卖出金额 ¥{float(reconciliation.get('sell_amount') or 0):,.0f} "
                f"= 持仓市值变动 ¥{float(reconciliation.get('stock_mv_delta') or 0):+,.0f}"
            )
        if reconciliation.get("identity_diff") is not None and not reconciliation.get("ok"):
            lines.append(
                f"  - 现金偏差 ¥{float(reconciliation['identity_diff']):+,.2f}，"
                f"持仓偏差 ¥{float(reconciliation.get('stock_identity_diff') or 0):+,.2f}，请核对 ledger 与收盘 manifest"
            )
    lines.append("")
    return lines


def render_holdings_sector_markdown(snapshot: dict[str, Any]) -> list[str]:
    if not snapshot:
        return []
    lines = ["## 🏭 持仓相关板块"]
    label = str(snapshot.get("as_of_label") or "")
    if label:
        lines.append(f"- **数据截止：** {label}")
    if not snapshot.get("fetch_ok"):
        lines.append(f"- {snapshot.get('fetch_error') or '⚠️ 数据获取失败'}")
    sectors = snapshot.get("sectors") or []
    if not sectors:
        lines.append("- 暂无持仓板块数据")
    else:
        for row in sectors[:6]:
            avg = row.get("avg_change_pct")
            avg_s = f"{float(avg):+.2f}%" if avg is not None else "—"
            names = "、".join(str(s.get("name") or s.get("code")) for s in row.get("symbols") or [])[:80]
            lines.append(f"- **{row.get('sector')}** {avg_s} · {names}")
    lines.append("")
    return lines
