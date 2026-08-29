# -*- coding: utf-8
"""Midday card content scope — compact market brief, macro impact, stock-only risks."""

from __future__ import annotations

import re
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

MIDDAY_PLAN_UNCHANGED = "维持早盘计划"

_PM_SESSION_NODES: tuple[tuple[str, str, str], ...] = (
    ("13:00", "下午开盘", "—"),
    ("13:05", "S8 盘中扫描", "确认 Lookback 与趋势"),
)
_MACRO_EVENT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"美联储|Fed|鲍威尔|非农|CPI|PPI", "14:00", "科技股波动"),
    (r"复牌|暂停上市", "14:30", "个股波动"),
)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holding_change_pct(holding: dict[str, Any]) -> Optional[float]:
    prev = _optional_float(holding.get("prev_close") or holding.get("pre_close"))
    price = _optional_float(holding.get("price") or holding.get("open"))
    if prev is None or prev <= 0 or price is None:
        return None
    return round((price - prev) / prev * 100.0, 2)


def _resolve_indices(enriched: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = enriched.get("sources") or {}
    quote = sources.get("quote")
    if isinstance(quote, dict) and quote.get("indices"):
        raw = quote.get("indices")
        if isinstance(raw, dict):
            return raw
    cached = enriched.get("indices")
    if isinstance(cached, dict):
        return cached
    try:
        from agent_reach.daily_run.eastmoney_market import fetch_indices

        return fetch_indices(timeout=8.0)
    except Exception:
        return {}


def build_am_market_key_points(
    enriched: dict[str, Any],
    *,
    portfolio: Optional[dict[str, Any]] = None,
    limit: int = 5,
) -> list[str]:
    """3-5 comma-ready AM market stats (indices, volume, leading theme)."""
    pf = portfolio or enriched.get("portfolio") or {}
    signals = enriched.get("macro_signals") or {}
    indices = _resolve_indices(enriched)
    points: list[str] = []

    sh_pct = _optional_float(signals.get("index_change_pct"))
    if sh_pct is None:
        sh_pct = _optional_float((indices.get("sh000001") or {}).get("change_pct"))
    if sh_pct is not None:
        points.append(f"上证 {sh_pct:+.1f}%")

    cyb_pct = _optional_float((indices.get("sz399006") or {}).get("change_pct"))
    if cyb_pct is not None:
        points.append(f"创业板 {cyb_pct:+.1f}%")

    sh_amt = _optional_float((indices.get("sh000001") or {}).get("amount"))
    sz_amt = _optional_float((indices.get("sz399001") or {}).get("amount"))
    if sh_amt is not None and sz_amt is not None and (sh_amt + sz_amt) > 0:
        total_yi = (sh_amt + sz_amt) / 1e8
        if total_yi >= 100:
            points.append(f"成交额 {total_yi:.0f}亿")
        else:
            points.append(f"成交额 {total_yi:.1f}亿")

    flow = _optional_float(signals.get("northbound_flow_yi"))
    if flow is not None and abs(flow) >= 5:
        points.append(f"北向 {flow:+.0f}亿")

    leader = _leading_theme_label(enriched, pf, indices)
    if leader:
        points.append(leader)

    if len(points) < 3:
        avg = _portfolio_avg_change(pf)
        if avg is not None:
            points.append(f"持仓均 {avg:+.1f}%")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in points:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:limit]


def _portfolio_avg_change(portfolio: dict[str, Any]) -> Optional[float]:
    vals: list[float] = []
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        pct = _holding_change_pct(row)
        if pct is not None:
            vals.append(pct)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _leading_theme_label(
    enriched: dict[str, Any],
    portfolio: dict[str, Any],
    indices: dict[str, dict[str, Any]],
) -> Optional[str]:
    best_sector = ""
    best_pct: Optional[float] = None
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        pct = _holding_change_pct(row)
        if pct is None:
            continue
        label = str(row.get("sector") or row.get("industry") or "").strip()
        if not label:
            continue
        if best_pct is None or pct > best_pct:
            best_pct = pct
            best_sector = label
    if best_sector and best_pct is not None and best_pct >= 0.8:
        return f"{best_sector}板块领涨"

    try:
        from agent_reach.daily_run.market_review import load_market_review
        from agent_reach.daily_run.trade_calendar import today_shanghai

        review = load_market_review(today_shanghai().isoformat())
        mainline = str((review or {}).get("dominant_mainline") or "").strip()
        if mainline and mainline not in {"—", "-"}:
            return f"{mainline}主线活跃"
    except Exception:
        pass

    hot = (enriched.get("macro_signals") or {}).get("portfolio_hot_stocks") or []
    if hot:
        name = str(hot[0].get("name") or hot[0].get("keyword") or "").strip()
        if name:
            return f"{name[:8]}舆情活跃"
    return None


def build_macro_holdings_impact_line(
    enriched: dict[str, Any],
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """One sentence: macro view + impact on holdings."""
    pf = portfolio or enriched.get("portfolio") or {}
    signals = enriched.get("macro_signals") or {}
    sources = enriched.get("sources") or {}

    try:
        from agent_reach.daily_run.morning_content_scope import (
            infer_affected_sectors,
            infer_impact_label,
            select_macro_headlines,
        )

        featured, _extra = select_macro_headlines(
            macro_signals=signals,
            sources=sources,
            portfolio=pf,
            limit=1,
        )
        if featured:
            title = str(featured[0].get("title") or "").strip()[:48]
            sectors = infer_affected_sectors(title, pf) or "持仓板块"
            impact = infer_impact_label(title)
            if impact == "利好":
                effect = f"{sectors}受益"
            elif impact == "利空":
                effect = f"{sectors}承压"
            else:
                effect = f"{sectors}波动有限"
            return f"宏观：{title}，对持仓影响：{effect}"
    except Exception:
        pass

    idx = _optional_float(signals.get("index_change_pct"))
    if idx is None:
        indices = _resolve_indices(enriched)
        idx = _optional_float((indices.get("sh000001") or {}).get("change_pct"))
    if idx is not None:
        if idx >= 0.8:
            return "宏观：大盘偏强，对持仓影响：整体风险偏好抬升"
        if idx <= -0.8:
            return "宏观：大盘偏弱，对持仓影响：宜控制仓位、优先防守"
        return "宏观：大盘震荡，对持仓影响：以个股计划为主"

    avg = _portfolio_avg_change(pf)
    if avg is not None:
        if avg >= 1.0:
            return "宏观：持仓整体偏强，对持仓影响：可按计划执行"
        if avg <= -1.0:
            return "宏观：持仓整体走弱，对持仓影响：优先风控"
    return ""


def build_morning_reference_line(
    morning_handoff: Optional[dict[str, Any]],
    *,
    close_handoff: Optional[dict[str, Any]] = None,
) -> str:
    """Brief '早盘提到 XXX' when a prior judgment still matters."""
    for action in (morning_handoff or {}).get("action_checklist") or []:
        if not isinstance(action, dict):
            continue
        trigger = str(action.get("trigger") or "").strip()
        operation = str(action.get("operation") or "").strip()
        if trigger and trigger not in {"—", "-"}:
            name = str(action.get("name") or action.get("code") or "").strip()
            snippet = f"{name}{operation}{trigger}" if name else f"{operation}{trigger}"
            return f"早盘提到 {snippet[:56]}"
        reasoning = str(action.get("reasoning") or action.get("note") or "").strip()
        if reasoning:
            return f"早盘提到 {reasoning[:56]}"

    for item in (close_handoff or {}).get("tomorrow_focus") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return f"早盘提到 {text[:56]}"
    return ""


def build_holding_risk_lines(
    *,
    portfolio: dict[str, Any],
    enriched: dict[str, Any],
    evaluation: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    limit: int = 5,
) -> list[str]:
    """Stock-specific afternoon risks for current holdings only."""
    from agent_reach.daily_run.close_morning_handoff import (
        _assess_risk_status,
        load_close_handoff_for_morning,
    )

    holding_codes = {
        _normalize_code(str(row.get("code") or ""))
        for row in (portfolio.get("holdings") or [])
        if isinstance(row, dict) and row.get("code")
    }
    if not holding_codes:
        return []

    close_handoff = load_close_handoff_for_morning(settings=settings)
    report = (evaluation or {}).get("report") or {}
    lines: list[str] = []

    for item in (close_handoff or {}).get("watch_risks") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(str(item.get("code") or ""))
        if code and code not in holding_codes:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        name = str(item.get("name") or code or "—")
        holding = _find_holding(portfolio, code, name)
        status, detail = _assess_risk_status(text, holding, enriched, report)
        if status == "仍待观察" and detail in {"数据不足", "—"}:
            continue
        lines.append(f"- **{name}** {detail}（{status}）")
        if len(lines) >= limit:
            break
    return lines


def _find_holding(portfolio: dict[str, Any], code: str, name: str) -> dict[str, Any]:
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        if code and _normalize_code(str(row.get("code") or "")) == code:
            return dict(row)
        if name and str(row.get("name") or "") == name:
            return dict(row)
    return {}


def compact_afternoon_display(row: dict[str, Any]) -> str:
    if row.get("data_stale"):
        return "⚠️ 待行情更新"
    if not row.get("changed"):
        return MIDDAY_PLAN_UNCHANGED
    action = str(row.get("afternoon_action") or MIDDAY_PLAN_UNCHANGED).strip()
    for prefix in (
        "截至 11:30 收盘 · ",
        "上午实际走势超预期，调整下午预测 · ",
    ):
        if action.startswith(prefix):
            action = action[len(prefix) :]
    return action or MIDDAY_PLAN_UNCHANGED


def _parse_level_from_text(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?", str(text or ""))
    if match:
        return float(match.group(1))
    return None


def format_trigger_cond(trigger: str) -> str:
    raw = str(trigger or "").strip()
    if not raw or raw in {"—", "-"}:
        return "—"
    level = _parse_level_from_text(raw)
    if level is not None:
        if "跌破" in raw:
            return f"跌破{level:g}"
        if "突破" in raw:
            return f"突破{level:g}"
        return f"{level:g}"
    return raw.replace("元", "").strip()[:20]


def format_verify_am_actual(
    *,
    operation: str,
    trigger: str,
    stats: dict[str, Optional[float]],
    change_pct: Optional[float],
    data_stale: bool,
) -> str:
    if data_stale:
        return "⚠️ 数据更新中"
    op = str(operation or "")
    trig = str(trigger or "")
    if op in ("减仓", "止损") or "跌破" in trig:
        low = stats.get("low")
        if low is not None:
            return f"最低{low:.2f}"
    if op == "加仓" or "突破" in trig:
        high = stats.get("high")
        if high is not None:
            return f"最高{high:.2f}"
    if change_pct is not None:
        return f"{change_pct:+.1f}%"
    return "—"


def format_verify_status(row: dict[str, Any]) -> str:
    if row.get("data_stale"):
        return "⚠️ 数据更新中"
    label = str(row.get("verify_label") or "")
    if row.get("filled") or label == "已成交":
        op = str(row.get("operation") or "")
        if op == "减仓":
            return "✅ 已减仓"
        return "✅ 已成交"
    if label == "已执行":
        return "✅ 已执行"
    if label == "未触发":
        return "❌ 未触发"
    if label == "触及未成交":
        return "⚠️ 触及未成交"
    if label in {"超预期", "偏弱"}:
        return "⚠️ 超预期"
    if label == "符合预期" or str(row.get("operation") or "") in {"观望", "持有"}:
        return "⏸️ 维持"
    return "⏸️ 维持"


def _derive_adjusted_operation(row: dict[str, Any]) -> str:
    afternoon = str(row.get("afternoon_action") or "")
    if not row.get("changed"):
        if row.get("filled"):
            return "维持"
        return str(row.get("operation") or "维持")
    if "减仓" in afternoon:
        return "减仓"
    if "观望" in afternoon or MIDDAY_PLAN_UNCHANGED in afternoon:
        return "观望"
    if "加仓" in afternoon:
        return "加仓"
    if "保守" in afternoon:
        return "观望"
    return str(row.get("operation") or "维持")


def _derive_adjust_reason(row: dict[str, Any], *, change_pct: Optional[float]) -> str:
    if row.get("filled"):
        op = str(row.get("operation") or "")
        if op == "减仓":
            return "已按计划减仓"
        if op == "加仓":
            return "已按计划加仓"
        return "已按计划执行"
    label = str(row.get("verify_label") or "")
    if label == "未触发":
        vol = row.get("volume_ratio")
        if vol is not None and float(vol) < 1.0:
            return "上午未突破，量能不足"
        return "上午未触发条件"
    if label == "超预期":
        vol = row.get("volume_ratio")
        if vol is not None and float(vol) >= 1.2 and change_pct is not None and change_pct > 0:
            return "上午放量冲高，技术面超买"
        return "上午走势超预期"
    if label == "偏弱":
        return "上午走弱，宜保守"
    if label == "触及未成交":
        return "价格触及但未成交"
    if not row.get("changed"):
        return "上午走势符合预期"
    return "下午策略微调"


def _derive_afternoon_trigger(row: dict[str, Any], stats: dict[str, Optional[float]]) -> str:
    afternoon = str(row.get("afternoon_action") or "")
    match = re.search(r"\*\*(\d+(?:\.\d+)?)\*\*", afternoon)
    if match:
        return f"反弹至{match.group(1)}"
    if "等待" in afternoon or "明确信号" in afternoon:
        return "等待明确信号"
    if row.get("filled"):
        return "—"
    if not row.get("changed"):
        return "—"
    stop = _parse_level_from_text(str(row.get("trigger") or ""))
    if stop is not None and "跌破" in str(row.get("afternoon_action") or ""):
        return f"跌破{stop:g}"
    price = stats.get("price")
    if price is not None and "止损" in afternoon:
        return f"跌破{price:.2f}"
    return "—"


def enrich_plan_row_signals(row: dict[str, Any]) -> dict[str, Any]:
    stats = dict(row.pop("stats", {}) or {})
    change_pct = row.get("change_pct")
    row["verify_operation"] = str(row.get("operation") or "—")
    row["trigger_cond"] = format_trigger_cond(str(row.get("trigger") or ""))
    row["verify_am_actual"] = format_verify_am_actual(
        operation=str(row.get("operation") or ""),
        trigger=str(row.get("trigger") or ""),
        stats=stats,
        change_pct=_optional_float(change_pct),
        data_stale=bool(row.get("data_stale")),
    )
    row["verify_status"] = format_verify_status(row)
    row["original_plan"] = str(row.get("operation") or "—")
    row["adjusted_plan"] = _derive_adjusted_operation(row)
    row["adjust_reason"] = _derive_adjust_reason(row, change_pct=_optional_float(change_pct))
    row["afternoon_trigger"] = _derive_afternoon_trigger(row, stats)
    row["operation_status"] = row["verify_status"].replace("✅ 已成交", "✅ 已减仓")
    return row


def build_holdings_am_brief_rows(
    *,
    portfolio: dict[str, Any],
    plan_rows: list[dict[str, Any]],
    enriched: dict[str, Any],
    am_scans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.morning_signals import _prev_close_value

    by_code = {_normalize_code(str(r.get("code") or "")): r for r in plan_rows if r.get("code")}
    rows: list[dict[str, Any]] = []
    for holding in portfolio.get("holdings") or []:
        if not isinstance(holding, dict):
            continue
        code = _normalize_code(str(holding.get("code") or ""))
        if not code:
            continue
        name = str(holding.get("name") or code)
        prev = _prev_close_value(holding, enriched)
        price = _optional_float(holding.get("price"))
        high = _optional_float(holding.get("high"))
        low = _optional_float(holding.get("low"))
        for scan in am_scans:
            px = _optional_float(scan.get("price"))
            if px is not None and px > 0:
                high = max(filter(None, [high, px]), default=high)
                low = min(filter(None, [low, px]), default=low)
        change_pct = _holding_change_pct(holding)
        vol = _optional_float(holding.get("volume_ratio") or enriched.get("volume_ratio"))
        plan = by_code.get(code) or {}
        rows.append(
            {
                "code": code,
                "name": name,
                "prev_close": prev,
                "am_close": price,
                "change_pct": change_pct,
                "am_high": high,
                "am_low": low,
                "volume_ratio": vol,
                "operation_status": plan.get("operation_status")
                or plan.get("verify_status")
                or "⏸️ 持有",
            }
        )
    return rows


def build_morning_prediction_verify_lines(
    *,
    morning_handoff: Optional[dict[str, Any]],
    close_handoff: Optional[dict[str, Any]],
    portfolio: dict[str, Any],
    enriched: dict[str, Any],
    limit: int = 2,
) -> list[str]:
    from agent_reach.daily_run.morning_signals import _prediction_hit

    lines: list[str] = []
    seen: set[str] = set()

    def _append(name: str, prediction: str, holding: dict[str, Any]) -> None:
        if not prediction or name in seen:
            return
        pct = _holding_change_pct(holding)
        if pct is None:
            return
        hit = _prediction_hit(prediction, holding, enriched)
        mark = "✅" if hit else "❌"
        tail = "符合预期" if hit else "超预期"
        lines.append(
            f'- 早盘预测"{name}{prediction[:16]}" → {mark} 上午实际{pct:+.2f}%，{tail}'
        )
        seen.add(name)

    for item in (close_handoff or {}).get("tomorrow_focus") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(str(item.get("code") or ""))
        name = str(item.get("name") or code or "").strip()
        text = str(item.get("text") or "").strip()
        if not name or not text:
            continue
        holding = _find_holding(portfolio, code, name)
        _append(name, text, holding)
        if len(lines) >= limit:
            return lines[:limit]

    for action in (morning_handoff or {}).get("action_checklist") or []:
        if not isinstance(action, dict):
            continue
        code = _normalize_code(str(action.get("code") or ""))
        name = str(action.get("name") or code or "").strip()
        note = str(action.get("reasoning") or action.get("note") or action.get("target_position") or "").strip()
        if not name or not note:
            continue
        holding = _find_holding(portfolio, code, name)
        _append(name, note, holding)
        if len(lines) >= limit:
            break
    return lines[:limit]


def build_am_anomaly_signals(
    *,
    enriched: dict[str, Any],
    portfolio: dict[str, Any],
    plan_rows: list[dict[str, Any]],
    market_key_points: list[str],
) -> list[str]:
    lines: list[str] = []
    for row in plan_rows:
        name = str(row.get("name") or "")
        pct = _optional_float(row.get("change_pct"))
        vol = _optional_float(row.get("volume_ratio"))
        code = _normalize_code(str(row.get("code") or ""))
        holding = _find_holding(portfolio, code, name)
        ma20 = _optional_float(holding.get("ma20") or enriched.get("ma20"))
        price = _optional_float(holding.get("price"))
        if pct is not None and pct <= -3.0 and vol is not None and vol >= 1.2:
            detail = f"上午放量下跌 {pct:.2f}%，量比 {vol:.1f}x"
            if ma20 is not None and price is not None and price < ma20:
                detail += "，跌破 20 日均线，下午关注是否继续下探"
            lines.append(f"- 🔴 **{name}**{detail}")
        elif pct is not None and pct >= 3.0 and vol is not None and vol >= 1.3:
            lines.append(f"- 🟡 **{name}** 上午放量上涨 {pct:+.2f}%，量比 {vol:.1f}x，注意冲高回落")

    sector_pcts: dict[str, list[float]] = {}
    for holding in portfolio.get("holdings") or []:
        if not isinstance(holding, dict):
            continue
        sector = str(holding.get("sector") or holding.get("industry") or "").strip()
        pct = _holding_change_pct(holding)
        if sector and pct is not None:
            sector_pcts.setdefault(sector, []).append(pct)
    if len(sector_pcts) >= 2:
        avgs = {k: sum(v) / len(v) for k, v in sector_pcts.items()}
        best = max(avgs, key=avgs.get)
        worst = min(avgs, key=avgs.get)
        if avgs[best] - avgs[worst] >= 1.5:
            lines.append(
                f"- 🟡 **{worst}** 板块上午整体{'走弱' if avgs[worst] < 0 else '震荡'}，"
                f"但 **{best}** 细分{'逆势上涨' if avgs[best] > 0 else '相对抗跌'}，板块内部分化加剧"
            )

    volume_line = next((p for p in market_key_points if p.startswith("成交额")), "")
    if volume_line:
        lines.append(f"- 🟡 大盘{volume_line}，下午关注量能是否恢复")

    return lines[:5]


def build_afternoon_timeline_nodes(
    *,
    enriched: dict[str, Any],
    portfolio: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = [
        {"time": t, "event": ev, "impact": imp} for t, ev, imp in _PM_SESSION_NODES
    ]
    seen: set[str] = set()

    def _add(time_s: str, event: str, impact: str) -> None:
        key = f"{time_s}:{event}"
        if key in seen:
            return
        seen.add(key)
        nodes.append({"time": time_s, "event": event[:48], "impact": impact[:32]})

    texts: list[str] = []
    signals = enriched.get("macro_signals") or {}
    for bucket in ("hot_topics_matched", "hot_topics"):
        for item in signals.get(bucket) or []:
            texts.append(str((item or {}).get("title") if isinstance(item, dict) else item))
    blob = "；".join(texts)
    for pattern, time_s, impact in _MACRO_EVENT_PATTERNS:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            match = re.search(pattern, blob, flags=re.IGNORECASE)
            label = match.group(0) if match else "宏观事件"
            _add(time_s, label, impact)

    try:
        from agent_reach.daily_run.tradability import is_suspended

        for holding in portfolio.get("holdings") or []:
            if not isinstance(holding, dict):
                continue
            merged = {**enriched, **holding}
            if is_suspended(merged):
                name = str(holding.get("name") or holding.get("code") or "个股")
                _add("14:30", f"{name}复牌/交易状态变化", "个股波动")
    except Exception:
        pass

    cfg = (settings or {}).get("midday") or {}
    for item in cfg.get("time_nodes") or []:
        if not isinstance(item, dict):
            continue
        _add(
            str(item.get("time") or "—"),
            str(item.get("event") or "—"),
            str(item.get("impact") or "—"),
        )

    nodes.sort(key=lambda r: r.get("time") or "")
    deduped: list[dict[str, str]] = []
    seen_rows: set[str] = set()
    for row in nodes:
        key = f"{row['time']}|{row['event']}"
        if key in seen_rows:
            continue
        seen_rows.add(key)
        deduped.append(row)
    return deduped[:8]


def render_verify_summary_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "**早盘计划验证汇总**",
        "",
        "| 股票 | 早盘计划 | 触发条件 | 上午实际 | 状态 |",
        "|------|----------|----------|----------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('name')} | {row.get('verify_operation')} | {row.get('trigger_cond')} "
            f"| {row.get('verify_am_actual')} | {row.get('verify_status')} |"
        )
    return lines


def render_adjustment_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "",
        "**下午操作调整清单**",
        "",
        "| 股票 | 原计划 | 调整后 | 调整原因 | 触发条件 |",
        "|------|--------|--------|----------|----------|",
    ]
    for row in rows:
        original = str(row.get("original_plan") or "—")
        if row.get("filled"):
            original = "—"
        lines.append(
            f"| {row.get('name')} | {original} | {row.get('adjusted_plan')} "
            f"| {row.get('adjust_reason')} | {row.get('afternoon_trigger')} |"
        )
    return lines


def render_timeline_table(nodes: list[dict[str, str]]) -> list[str]:
    if not nodes:
        return []
    lines = [
        "",
        "**下午时间节点**",
        "",
        "| 时间 | 事件 | 影响 |",
        "|------|------|------|",
    ]
    for row in nodes:
        lines.append(f"| {row.get('time')} | {row.get('event')} | {row.get('impact')} |")
    return lines


def render_holdings_am_brief_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "**持仓上午速览**",
        "",
        "| 股票 | 昨收 | 上午收盘 | 涨跌幅 | 上午最高 | 上午最低 | 量比 | 操作状态 |",
        "|------|------|----------|--------|----------|----------|------|----------|",
    ]
    for row in rows:
        prev_s = f"{float(row['prev_close']):.2f}" if row.get("prev_close") is not None else "—"
        price_s = f"{float(row['am_close']):.2f}" if row.get("am_close") is not None else "—"
        pct_s = f"{float(row['change_pct']):+.2f}%" if row.get("change_pct") is not None else "—"
        high_s = f"{float(row['am_high']):.2f}" if row.get("am_high") is not None else "—"
        low_s = f"{float(row['am_low']):.2f}" if row.get("am_low") is not None else "—"
        vol = row.get("volume_ratio")
        vol_s = f"{float(vol):.1f}x" if vol is not None else "—"
        lines.append(
            f"| {row.get('name')} | {prev_s} | {price_s} | {pct_s} | {high_s} | {low_s} "
            f"| {vol_s} | {row.get('operation_status') or '—'} |"
        )
    return lines
