# -*- coding: utf-8
"""Weekly report ↔ daily close card data loop (trades, holdings, predictions, outlook)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_OUTLOOK_DIR = Path.home() / ".agent-reach" / "daily_run" / "weekly_outlook"


def _weekday_label(ds: str) -> str:
    try:
        return _WEEKDAY_CN[date.fromisoformat(ds[:10]).weekday()]
    except ValueError:
        return ds[:10]


def _close_card_ref(ds: str) -> str:
    return f"详见{_weekday_label(ds)}收盘卡片"


def _portfolio_summary_from_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.weekly_report import _portfolio_summary_from_manifest

    return _portfolio_summary_from_manifest(record)


def iter_week_close_manifests(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> list[dict[str, Any]]:
    rows = [
        m
        for m in manifests
        if m.get("job") == "close"
        and week_start.isoformat() <= str(m.get("_run_date") or "")[:10] <= week_end.isoformat()
    ]
    return sorted(rows, key=lambda m: str(m.get("_run_date") or ""))


def aggregate_close_card_trades(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> list[dict[str, Any]]:
    """Merge Mon–Fri close-card「实际成交」into weekly trade rows."""
    from agent_reach.daily_run.close_portfolio_summary import extract_close_trade_operations

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in iter_week_close_manifests(manifests, week_start=week_start, week_end=week_end):
        ds = str(record.get("_run_date") or "")[:10]
        ps = _portfolio_summary_from_record(record)
        if not ps:
            continue
        for op in extract_close_trade_operations(ps):
            side_raw = str(op.get("side") or "")
            if side_raw not in ("buy", "sell"):
                continue
            key = (ds, op.get("code"), side_raw, op.get("shares"), op.get("price"))
            if key in seen:
                continue
            seen.add(key)
            side = "买" if side_raw == "buy" else "卖"
            name = str(op.get("name") or op.get("code") or "")
            shares = int(op.get("shares") or 0)
            price = op.get("price")
            if price is not None and shares:
                operation = f"{side}{name} {shares}股@{float(price):.2f}"
            elif shares:
                operation = f"{side}{name} {shares}股"
            else:
                operation = f"{side}{name}"
            rows.append(
                {
                    "date": ds,
                    "code": _normalize_code(str(op.get("code") or "")),
                    "name": name,
                    "side": side,
                    "side_raw": side_raw,
                    "price": price,
                    "shares": shares,
                    "amount": op.get("amount"),
                    "commission": op.get("commission"),
                    "operation": operation,
                    "pnl": op.get("realized_pnl"),
                    "source": "close_card",
                    "close_ref": _close_card_ref(ds),
                }
            )
    rows.sort(key=lambda r: (r.get("date") or "", r.get("code") or ""))
    return rows


def merge_weekly_trade_sources(
    close_trades: list[dict[str, Any]],
    ledger_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer close-card trades; fill gaps from ledger."""
    merged = list(close_trades)
    seen = {
        (r.get("date"), r.get("code"), r.get("side_raw"), r.get("shares"), r.get("price"))
        for r in close_trades
    }
    for row in ledger_trades:
        key = (row.get("date"), row.get("code"), row.get("side_raw"), row.get("shares"), row.get("price"))
        if key in seen:
            continue
        merged.append({**row, "source": row.get("source") or "ledger"})
    merged.sort(key=lambda r: (r.get("date") or "", r.get("code") or ""))
    return merged


def resolve_friday_close_portfolio(
    end_record: Optional[dict[str, Any]],
    pf_fallback: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Holdings/cash from Friday close card portfolio_summary (final state)."""
    if not end_record:
        return pf_fallback, list(pf_fallback.get("holdings") or []), "portfolio.json"
    ps = _portfolio_summary_from_record(end_record)
    if ps and ps.get("holdings"):
        pf = dict(pf_fallback)
        pf["holdings"] = [dict(h) for h in ps["holdings"]]
        if ps.get("cash") is not None:
            pf["cash"] = ps["cash"]
        if ps.get("cash_ratio") is not None:
            pf["cash_ratio"] = ps["cash_ratio"]
        if ps.get("watchlist"):
            pf["watchlist"] = [dict(w) for w in ps["watchlist"]]
        ds = str(end_record.get("_run_date") or "")[:10]
        return pf, pf["holdings"], f"周五收盘卡片（{ds}）"
    from agent_reach.daily_run.weekly_report import _merged_enriched_from_manifest

    snap_end, _ = _merged_enriched_from_manifest(end_record)
    if snap_end:
        pf_end = dict(snap_end.get("portfolio") or {})
        if pf_end.get("holdings"):
            pf = dict(pf_fallback)
            pf["holdings"] = [dict(h) for h in pf_end["holdings"]]
            if pf_end.get("cash") is not None:
                pf["cash"] = pf_end["cash"]
            ds = str(end_record.get("_run_date") or "")[:10]
            return pf, pf["holdings"], f"周五收盘 manifest（{ds}）"
    return pf_fallback, list(pf_fallback.get("holdings") or []), "portfolio.json"


def summarize_close_card_predictions(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    """Aggregate daily close-card forecast_verify into weekly stats."""
    from agent_reach.daily_run.weekly_content_scope import summarize_week_prediction_verification

    base = summarize_week_prediction_verification(manifests, week_start=week_start, week_end=week_end)
    daily_rows: list[dict[str, Any]] = []
    for record in iter_week_close_manifests(manifests, week_start=week_start, week_end=week_end):
        ds = str(record.get("_run_date") or "")[:10]
        from agent_reach.daily_run.weekly_content_scope import _manifest_close_forecast

        forecast = _manifest_close_forecast(record)
        if not forecast:
            continue
        evals = forecast.get("symbol_evals") or []
        total = int(forecast.get("symbol_total") or 0)
        hits = int(forecast.get("symbol_hits") or 0)
        if not total and evals:
            total = len(evals)
            hits = sum(1 for e in evals if e.get("hit"))
        acc = forecast.get("accuracy")
        if acc is None and total:
            acc = hits / total
        mss_hit = forecast.get("mss_hit")
        daily_rows.append(
            {
                "date": ds,
                "weekday": _weekday_label(ds),
                "symbol_hits": hits,
                "symbol_total": total,
                "accuracy_pct": round(float(acc) * 100.0, 1) if acc is not None and acc <= 1 else acc,
                "mss_hit": mss_hit,
                "close_ref": _close_card_ref(ds),
            }
        )
    base["daily_rows"] = daily_rows
    base["source"] = "close_card"
    base["close_card_days"] = len(daily_rows)
    return base


def build_close_loop_position_change(
    manifests: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
    start_record: Optional[dict[str, Any]],
    end_record: Optional[dict[str, Any]],
    close_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Mon open vs Fri close exposure, with per-day close-card position notes."""
    start_exposure: Optional[float] = None
    end_exposure: Optional[float] = None
    start_source = ""
    end_source = ""

    if start_record:
        ps = _portfolio_summary_from_record(start_record)
        if ps:
            start_exposure = ps.get("stock_ratio")
            if start_exposure is not None:
                start_exposure = round(float(start_exposure) * 100.0, 1)
            start_source = f"{str(start_record.get('_run_date') or '')[:10]} 收盘卡片"
        if start_exposure is None:
            from agent_reach.daily_run.weekly_report import _portfolio_parts_from_manifest

            _, start_mv = _portfolio_parts_from_manifest(start_record)
            total = ps.get("start_total") if ps else None
            if total and start_mv is not None and float(total) > 0:
                start_exposure = round(float(start_mv) / float(total) * 100.0, 1)
                start_source = f"{str(start_record.get('_run_date') or '')[:10]} 早盘/收盘"

    if end_record:
        ps_end = _portfolio_summary_from_record(end_record)
        if ps_end:
            ratio = ps_end.get("stock_ratio")
            if ratio is not None:
                end_exposure = round(float(ratio) * 100.0, 1)
            elif ps_end.get("end_total") and ps_end.get("stock_mv"):
                end_exposure = round(float(ps_end["stock_mv"]) / float(ps_end["end_total"]) * 100.0, 1)
            end_source = f"{str(end_record.get('_run_date') or '')[:10]} 收盘卡片"

    daily_notes: list[str] = []
    trend_parts: list[str] = []
    for record in iter_week_close_manifests(manifests, week_start=week_start, week_end=week_end):
        ds = str(record.get("_run_date") or "")[:10]
        ps = _portfolio_summary_from_record(record)
        if not ps:
            continue
        ratio = ps.get("stock_ratio")
        if ratio is not None:
            trend_parts.append(f"{ds[5:]}:{round(float(ratio)*100):.0f}%")
        change = str(ps.get("position_change") or "").strip()
        if change and change != "无调仓":
            daily_notes.append(f"{_weekday_label(ds)} {change}")

    trade_reasons: list[str] = []
    end_total = None
    if end_record:
        ps_end = _portfolio_summary_from_record(end_record)
        end_total = _optional_float((ps_end or {}).get("end_total"))
    for row in close_trades:
        ds = str(row.get("date") or "")[:10]
        name = str(row.get("name") or "")
        side = str(row.get("side") or "")
        amount = _optional_float(row.get("amount")) or 0.0
        if not name or not side:
            continue
        if end_total and end_total > 0:
            delta = round(amount / end_total * 100.0, 1)
            trade_reasons.append(
                f"{_weekday_label(ds)}{side}{name} {'+' if side == '买' else '-'}{delta}%"
            )

    reason_parts = daily_notes[:3] or trade_reasons[:4]
    market_part = ""
    if start_exposure is not None and end_exposure is not None:
        trade_effect = sum(
            (float(r.get("amount") or 0) / float(end_total) * 100.0)
            * (-1 if r.get("side_raw") == "buy" else 1 if r.get("side_raw") == "sell" else 0)
            for r in close_trades
            if end_total and end_total > 0
        )
        implied = round(end_exposure - start_exposure - trade_effect, 1)
        if abs(implied) >= 0.1:
            market_part = f"其余为市值波动 {implied:+.1f}%"

    reason_text = "，".join(reason_parts)
    if market_part:
        reason_text = (reason_text + "，" if reason_text else "") + market_part
    if not reason_text:
        reason_text = "本周无收盘卡片调仓记录，变化主要来自市值波动"

    return {
        "start_exposure_pct": start_exposure,
        "end_exposure_pct": end_exposure,
        "start_source": start_source,
        "end_source": end_source,
        "daily_notes": daily_notes,
        "reason_text": reason_text,
        "trend_text": " → ".join(trend_parts[:5]),
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def outlook_plan_path(week_end: date) -> Path:
    return _OUTLOOK_DIR / f"{week_end.isoformat()}.json"


def save_weekly_outlook_plan(
    *,
    week_end: date,
    week_start: date,
    next_week_outlook: dict[str, Any],
    target_week_start: date,
    target_week_end: date,
) -> Path:
    _OUTLOOK_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "saved_week_end": week_end.isoformat(),
        "saved_week_start": week_start.isoformat(),
        "target_week_start": target_week_start.isoformat(),
        "target_week_end": target_week_end.isoformat(),
        "operation_plan": next_week_outlook.get("operation_plan") or [],
        "risk_calendar": next_week_outlook.get("risk_calendar") or [],
    }
    path = outlook_plan_path(week_end)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_outlook_plan_for_backtrack(current_week_start: date) -> Optional[dict[str, Any]]:
    """Load the outlook plan that targeted the week being reviewed."""
    if not _OUTLOOK_DIR.is_dir():
        return None

    target_start = current_week_start.isoformat()

    def _match(data: dict[str, Any]) -> bool:
        return str(data.get("target_week_start") or "") == target_start

    for path in sorted(_OUTLOOK_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _match(data):
            data["_path"] = str(path)
            return data

    from agent_reach.daily_run.weekly_report import trading_week_range

    prior_ws, prior_we = trading_week_range(current_week_start - timedelta(days=7))
    prior_path = outlook_plan_path(prior_we)
    if prior_path.is_file():
        try:
            data = json.loads(prior_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if _match(data):
            data["_path"] = str(prior_path)
            return data
        _ = prior_ws
    return None


def synthesize_outlook_plan_for_backtrack(
    current_week_start: date,
    current_week_end: date,
    *,
    settings: Optional[dict[str, Any]] = None,
    holdings: Optional[list[dict[str, Any]]] = None,
    watchlist_intel: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Rebuild last week's saved outlook when the JSON file is missing."""
    from agent_reach.daily_run.week_forecast import next_trading_week_range
    from agent_reach.daily_run.weekly_report import trading_week_range
    from agent_reach.daily_run.weekly_signals import build_next_week_outlook

    prior_ws, prior_we = trading_week_range(current_week_start - timedelta(days=7))
    next_start, next_end = next_trading_week_range(prior_we + timedelta(days=1))
    if next_start != current_week_start or next_end != current_week_end:
        return None

    outlook = build_next_week_outlook(
        week_end=prior_we,
        holdings=list(holdings or []),
        watchlist=[],
        settings=settings,
        watchlist_intel=watchlist_intel,
    )
    operation_plan = outlook.get("operation_plan") or []
    if not operation_plan:
        return None
    return {
        "saved_week_end": prior_we.isoformat(),
        "saved_week_start": prior_ws.isoformat(),
        "target_week_start": current_week_start.isoformat(),
        "target_week_end": current_week_end.isoformat(),
        "operation_plan": operation_plan,
        "risk_calendar": outlook.get("risk_calendar") or [],
        "_synthesized": True,
    }


def resolve_target_week_holdings_for_backtrack(
    manifests: list[dict[str, Any]],
    *,
    target_start: date,
    target_end: date,
) -> list[dict[str, Any]]:
    """Friday close-card holdings for the plan target week (PnL backtrack)."""
    close_rows = iter_week_close_manifests(
        manifests,
        week_start=target_start,
        week_end=target_end,
    )
    if not close_rows:
        return []
    ps = _portfolio_summary_from_record(close_rows[-1])
    if ps and ps.get("holdings"):
        return [dict(h) for h in ps["holdings"]]
    from agent_reach.daily_run.weekly_report import _merged_enriched_from_manifest

    snap_end, _ = _merged_enriched_from_manifest(close_rows[-1])
    if snap_end:
        pf_end = dict(snap_end.get("portfolio") or {})
        if pf_end.get("holdings"):
            return [dict(h) for h in pf_end["holdings"]]
    return []


def verify_outlook_plan_execution(
    plan: dict[str, Any],
    *,
    manifests: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    close_trades: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    target_start = date.fromisoformat(str(plan["target_week_start"]))
    target_end = date.fromisoformat(str(plan["target_week_end"]))
    week_trades = aggregate_close_card_trades(
        manifests,
        week_start=target_start,
        week_end=target_end,
    )
    holdings_by_code = {_normalize_code(str(h.get("code") or "")): h for h in holdings}
    rows: list[dict[str, Any]] = []
    for item in plan.get("operation_plan") or []:
        code = _normalize_code(str(item.get("code") or ""))
        name = str(item.get("name") or code or "—")
        action = str(item.get("action") or "持有")
        matched_trade = next(
            (t for t in week_trades if _normalize_code(str(t.get("code") or "")) == code),
            None,
        )
        holding = holdings_by_code.get(code) or {}
        week_pnl = holding.get("week_chg")
        week_pnl_pct = holding.get("week_chg_pct")
        executed = matched_trade is not None
        if action in ("买入", "新建仓") and matched_trade and matched_trade.get("side_raw") == "buy":
            status = "✅ 已执行"
        elif action == "减仓" and matched_trade and matched_trade.get("side_raw") == "sell":
            status = "✅ 已执行"
        elif action == "持有" and not matched_trade:
            status = "✅ 持有"
        elif action == "持有" and matched_trade:
            status = "⚠️ 有交易"
        else:
            status = "❌ 未执行" if action != "持有" else "—"
        pnl_s = ""
        if week_pnl is not None:
            pnl_s = f"盈亏 ¥{float(week_pnl):+,.0f}"
        elif week_pnl_pct is not None:
            pnl_s = f"涨跌 {float(week_pnl_pct):+.2f}%"
        rows.append(
            {
                "name": name,
                "planned_action": action,
                "trigger": item.get("trigger"),
                "status": status,
                "executed": executed,
                "result": pnl_s or (matched_trade.get("operation") if matched_trade else "—"),
            }
        )
    done = sum(1 for r in rows if str(r.get("status", "")).startswith("✅"))
    return {
        "plan_saved_week_end": plan.get("saved_week_end"),
        "target_week_start": plan.get("target_week_start"),
        "target_week_end": plan.get("target_week_end"),
        "rows": rows,
        "executed_count": done,
        "total_count": len(rows),
        "synthesized": bool(plan.get("_synthesized")),
    }


def render_outlook_backtrack_markdown(backtrack: dict[str, Any]) -> list[str]:
    if not backtrack or not backtrack.get("rows"):
        return []
    synth_note = "（由上周收盘 handoff 重建）" if backtrack.get("synthesized") else ""
    lines = [
        "## 🔁 计划执行回溯",
        f"- _对照 {backtrack.get('target_week_start')} ~ {backtrack.get('target_week_end')} "
        f"（计划保存于 {backtrack.get('plan_saved_week_end')} 周报{synth_note}）_",
        "",
        "| 股票 | 计划操作 | 触发条件 | 执行结果 | 盈亏 |",
        "|------|----------|----------|----------|------|",
    ]
    for row in backtrack["rows"]:
        lines.append(
            f"| {row.get('name')} | {row.get('planned_action')} | {row.get('trigger', '—')} "
            f"| {row.get('status')} | {row.get('result', '—')} |"
        )
    total = int(backtrack.get("total_count") or 0)
    done = int(backtrack.get("executed_count") or 0)
    if total:
        lines.append("")
        lines.append(f"- **执行率：** {done}/{total}")
    lines.append("")
    return lines


def render_close_loop_trade_log_note(close_days: int, ledger_fallback: bool) -> str:
    parts = [f"来源：周一–周五收盘卡片实际成交汇总（{close_days} 个交易日）"]
    if ledger_fallback:
        parts.append("ledger 补充未落盘成交")
    return "_" + "；".join(parts) + "_"
