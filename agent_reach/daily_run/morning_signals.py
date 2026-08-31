# -*- coding: utf-8
"""Morning card signals — action checklist, holdings table, risks, time nodes, prediction verify."""

from __future__ import annotations

import re
from typing import Any, Optional

from agent_reach.daily_run.morning_content_scope import infer_impact_label, select_macro_headlines
from agent_reach.daily_run.snapshot_builder import _normalize_code

_SESSION_NODES: tuple[tuple[str, str, str], ...] = (
    ("09:30", "开盘", "定方向/量能"),
    ("11:30", "午间休市", "上午走势定调"),
    ("13:00", "午后开盘", "续势或反转"),
    ("14:57", "尾盘集合竞价", "收盘价博弈"),
    ("15:00", "收盘", "当日结果锁定"),
)

_MACRO_EVENT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"PMI|制造业", "10:00", "大盘波动"),
    (r"美联储|FOMC|鲍威尔", "14:00", "科技股波动"),
    (r"非农|CPI|PPI|GDP", "20:30", "外盘波动"),
    (r"股指期货|交割", "15:00", "指数波动"),
)

_HOLDING_RISK_KW = ("解禁", "财报", "披露", "立案", "调查", "减持", "质押", "退市")
_MARKET_RISK_KW = ("美联储", "PMI", "非农", "CPI", "交割", "制裁", "战争", "地缘")
_SECTOR_RISK_KW = ("监管", "整顿", "限价", "反垄断", "行业利空", "产能过剩")


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _action_operation(
    current_pct: float,
    target_pct: float,
    verdict: str,
) -> str:
    if target_pct < current_pct - 0.4:
        return "减仓"
    if target_pct > current_pct + 0.4:
        return "加仓"
    if verdict == "观察":
        return "观望"
    return "持有"


def _target_position_label(current_pct: float, target_pct: float) -> str:
    if abs(target_pct - current_pct) <= 0.4:
        return f"维持 {current_pct:.0f}%"
    return f"{current_pct:.0f}% → {target_pct:.0f}%"


def _close_handoff_trigger(code: str, ctx: Any) -> str:
    handoff = getattr(ctx, "close_handoff", None) or {}
    code_norm = _normalize_code(code)
    for item in handoff.get("tomorrow_focus") or []:
        if not isinstance(item, dict):
            continue
        item_code = _normalize_code(str(item.get("code") or ""))
        if not item_code or item_code != code_norm:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return text[:48]
    for item in handoff.get("watch_risks") or []:
        if not isinstance(item, dict):
            continue
        item_code = _normalize_code(str(item.get("code") or ""))
        if not item_code or item_code != code_norm:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return f"风险：{text[:40]}"
    return ""


def _monitor_trigger(
    *,
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    report: dict[str, Any],
) -> str:
    parts: list[str] = []
    stop = _optional_float(report.get("stop_loss_price"))
    entry = _optional_float(report.get("entry_price"))
    ma20 = _optional_float(holding.get("ma20") or snapshot.get("ma20"))
    if stop is not None:
        parts.append(f"止损 ≤ {stop:.2f} 元")
    if entry is not None:
        parts.append(f"突破 {entry:.2f} 元")
    if ma20 is not None:
        parts.append(f"MA20 {ma20:.2f} 元")
    invalidation = str(report.get("invalidation") or "").strip()
    if invalidation and len(parts) < 2:
        parts.append(invalidation[:32])
    return " · ".join(parts[:2]) if parts else ""


def _trigger_condition(
    *,
    operation: str,
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    report: dict[str, Any],
    suspended: bool,
    ctx: Any = None,
    code: str = "",
) -> str:
    if suspended:
        return "停牌"
    if operation in ("观望", "持有"):
        handoff_trig = _close_handoff_trigger(code, ctx) if ctx is not None else ""
        if handoff_trig:
            return handoff_trig
        monitor = _monitor_trigger(holding=holding, snapshot=snapshot, report=report)
        if monitor:
            return monitor
        mss = _optional_float(report.get("mss_final"))
        if mss is not None:
            return f"MSS {mss:.0f} 临界，突破/跌破跟进"
        return "—"

    stop = _optional_float(report.get("stop_loss_price"))
    entry = _optional_float(report.get("entry_price"))
    ma20 = _optional_float(holding.get("ma20") or snapshot.get("ma20"))
    prev = _optional_float(holding.get("prev_close") or snapshot.get("prev_close"))

    if operation == "减仓":
        if stop is not None:
            return f"价格 ≤ {stop:.2f} 元"
        if ma20 is not None:
            return f"跌破 MA20 {ma20:.2f} 元"
        if prev is not None:
            return f"开盘价 < {prev:.2f} 元"
        return "—"

    if operation == "加仓":
        if entry is not None:
            return f"突破 {entry:.2f} 元"
        if ma20 is not None:
            return f"站稳 MA20 {ma20:.2f} 元"
        return "—"

    return "—"


def build_action_checklist_rows(ctx: Any) -> list[dict[str, str]]:
    from agent_reach.daily_run.close_morning_handoff import close_position_weight
    from agent_reach.daily_run.morning_cards import (
        MorningCardContext,
        _target_position_pct,
    )
    from agent_reach.daily_run.tradability import is_suspended

    if not isinstance(ctx, MorningCardContext):
        return []

    rows: list[dict[str, str]] = []
    for sym in ctx.symbol_rows:
        holding = sym.holding or {}
        snap = sym.snapshot or {}
        report = sym.report or {}
        merged = {**snap, **holding}
        if int(holding.get("shares") or 0) <= 0:
            continue
        suspended = is_suspended(merged)
        current = close_position_weight(ctx, sym.code, fallback_holding=holding)
        if current is None:
            continue
        target, _source = _target_position_pct(
            report,
            snap,
            current_pct=current,
            settings=ctx.settings,
        )
        verdict = str(report.get("verdict") or "观察")
        operation = _action_operation(current, target, verdict)
        rows.append(
            {
                "code": sym.code,
                "name": sym.name,
                "operation": operation,
                "trigger": _trigger_condition(
                    operation=operation,
                    holding=holding,
                    snapshot=snap,
                    report=report,
                    suspended=suspended,
                    ctx=ctx,
                    code=sym.code,
                ),
                "target_position": _target_position_label(current, target),
                "current_weight_pct": round(current, 1),
                "target_weight_pct": round(target, 1),
            }
        )
    return rows


def render_action_checklist_markdown(ctx: Any) -> str:
    rows = build_action_checklist_rows(ctx)
    if not rows:
        return ""

    lines = [
        "**今日操作清单**",
        "",
        "| 股票 | 操作 | 触发条件 | 目标仓位 |",
        "|------|------|----------|----------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['operation']} | {row['trigger']} | {row['target_position']} |"
        )

    time_md = render_time_nodes_markdown(collect_time_nodes(ctx))
    if time_md:
        lines.extend(["", time_md])
    return "\n".join(lines).strip()


def _prev_close_value(holding: dict[str, Any], snapshot: dict[str, Any]) -> Optional[float]:
    from agent_reach.daily_run.morning_cards import _reference_price

    return _reference_price(holding, snapshot)


def _change_pct_vs_prev(
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    suspended: bool,
) -> str:
    if suspended:
        return "—"
    prev = _prev_close_value(holding, snapshot)
    open_px = _optional_float(holding.get("open") or snapshot.get("open"))
    price = _optional_float(holding.get("price") or snapshot.get("price"))
    ref = open_px if open_px is not None and open_px > 0 else price
    if prev is None or ref is None or prev <= 0:
        raw = holding.get("change_pct") if holding.get("change_pct") is not None else snapshot.get("change_pct")
        if raw is None:
            return "—"
        pct = float(raw)
        if abs(pct) <= 1.5 and pct != 0:
            pct *= 100.0
        return f"{pct:+.2f}%"
    pct = (ref - prev) / prev * 100.0
    return f"{pct:+.2f}%"


def _format_prev_close(holding: dict[str, Any], snapshot: dict[str, Any], *, suspended: bool) -> str:
    if suspended:
        return "—"
    prev = _prev_close_value(holding, snapshot)
    if prev is None:
        return "—"
    return f"{prev:.2f}"


def _format_open_price(holding: dict[str, Any], snapshot: dict[str, Any], *, suspended: bool) -> str:
    from agent_reach.daily_run.morning_cards import _format_open_cell

    cell = _format_open_cell(holding, snapshot, suspended=suspended)
    if cell.startswith("¥"):
        return cell[1:]
    if cell in ("待开盘", "🔒 停牌", "—"):
        return cell.replace("🔒 ", "")
    return cell


def _format_volume_ratio(holding: dict[str, Any], snapshot: dict[str, Any]) -> str:
    raw = holding.get("volume_ratio")
    if raw is None:
        raw = snapshot.get("volume_ratio")
    val = _optional_float(raw)
    if val is None:
        return "—"
    return f"{val:.1f}x"


def render_holdings_snapshot_table_markdown(ctx: Any) -> str:
    from agent_reach.daily_run.tradability import is_suspended

    if not ctx.symbol_rows:
        return ""

    lines = [
        "**持仓早盘速览**",
        "",
        "| 股票 | 昨收 | 今开 | 涨跌幅 | 成交量比 | MSS | 标签 |",
        "|------|------|------|--------|----------|-----|------|",
    ]
    for sym in ctx.symbol_rows:
        holding = sym.holding or {}
        snap = sym.snapshot or {}
        report = sym.report or {}
        merged = {**snap, **holding}
        suspended = is_suspended(merged)
        mss = report.get("mss_final")
        mss_s = f"{float(mss):.0f}" if mss is not None else "—"
        label = str(report.get("verdict") or "—")
        if label == "观察":
            label = "观望"
        lines.append(
            f"| {sym.name} | {_format_prev_close(holding, snap, suspended=suspended)} "
            f"| {_format_open_price(holding, snap, suspended=suspended)} "
            f"| {_change_pct_vs_prev(holding, snap, suspended=suspended)} "
            f"| {_format_volume_ratio(holding, snap)} | {mss_s} | {label} |"
        )
    return "\n".join(lines).strip()


def collect_time_nodes(ctx: Any) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = [{"time": t, "event": ev, "impact": imp} for t, ev, imp in _SESSION_NODES]
    seen_events: set[str] = set()

    def _add(time_s: str, event: str, impact: str) -> None:
        key = f"{time_s}:{event}"
        if key in seen_events:
            return
        seen_events.add(key)
        nodes.append({"time": time_s, "event": event[:48], "impact": impact[:32]})

    snap = ctx.primary_snapshot or {}
    texts: list[str] = []
    for bucket in ("hot_topics_matched", "hot_topics"):
        for item in (ctx.macro_signals or {}).get(bucket) or []:
            if isinstance(item, dict):
                texts.append(str(item.get("title") or ""))
            else:
                texts.append(str(item))
    hot_src = (snap.get("sources") or {}).get("hot_news") or {}
    if isinstance(hot_src, dict):
        texts.append(str(hot_src.get("summary") or ""))
    for narrative in (ctx.narrative or {}).get("focus_points") or []:
        texts.append(str(narrative))
    blob = "；".join(texts)

    for pattern, time_s, impact in _MACRO_EVENT_PATTERNS:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            match = re.search(pattern, blob, flags=re.IGNORECASE)
            label = match.group(0) if match else "宏观事件"
            _add(time_s, f"{label}公布/发布", impact)

    cfg = (ctx.settings or {}).get("morning") or {}
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
    seen: set[str] = set()
    for row in nodes:
        key = f"{row['time']}|{row['event']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:8]


def render_time_nodes_markdown(nodes: list[dict[str, str]]) -> str:
    if not nodes:
        return ""
    lines = [
        "**今日时间节点**",
        "",
        "| 时间 | 事件 | 影响 |",
        "|------|------|------|",
    ]
    for row in nodes:
        lines.append(f"| {row['time']} | {row['event']} | {row['impact']} |")
    return "\n".join(lines).strip()


def _collect_holding_risks(ctx: Any) -> list[str]:
    from agent_reach.daily_run.tradability import is_suspended

    risks: list[str] = []
    for sym in ctx.symbol_rows:
        holding = sym.holding or {}
        snap = sym.snapshot or {}
        report = sym.report or {}
        if int(holding.get("shares") or 0) <= 0:
            continue
        merged = {**snap, **holding}
        name = sym.name
        mss = _optional_float(report.get("mss_final"))
        if mss is not None and mss < 40:
            risks.append(f"**{name}** MSS {mss:.0f} 低于 macro_veto，禁止接飞刀")
        if str(report.get("verdict") or "") == "回避":
            risks.append(f"**{name}** 标签回避，优先减仓/清仓")
        if is_suspended(merged):
            risks.append(f"**{name}** 停牌，无法交易")
        price = _optional_float(holding.get("price") or snap.get("price"))
        stop = _optional_float(report.get("stop_loss_price"))
        ma20 = _optional_float(holding.get("ma20") or snap.get("ma20"))
        if price is not None and stop is not None and price <= stop:
            risks.append(f"**{name}** 已触止损 {stop:.2f}，技术破位")
        elif price is not None and ma20 is not None and price < ma20:
            risks.append(f"**{name}** 跌破 MA20 {ma20:.2f}，趋势走弱")
        text_blob = f"{report.get('invalidation') or ''} {report.get('reasoning') or ''}"
        for kw in _HOLDING_RISK_KW:
            if kw in text_blob:
                risks.append(f"**{name}** {kw}风险：{text_blob.strip()[:72]}")
                break
    return risks[:6]


def _collect_market_risks(ctx: Any) -> list[str]:
    risks: list[str] = []
    signals = ctx.macro_signals or {}
    flow = _optional_float(signals.get("northbound_flow_yi"))
    if flow is not None and flow <= -20:
        risks.append(f"北向大幅净流出 **{flow:.1f} 亿**，大盘承压")
    idx = _optional_float(signals.get("index_change_pct"))
    if idx is not None and idx <= -1.0:
        risks.append(f"A股指数偏弱 **{idx:+.2f}%**，控制仓位")

    snap = ctx.primary_snapshot or {}
    texts: list[str] = []
    featured, _extra = select_macro_headlines(
        macro_signals=signals,
        sources=snap.get("sources"),
        portfolio=ctx.portfolio,
        limit=5,
    )
    for row in featured:
        title = str(row.get("title") or "")
        if infer_impact_label(title) == "利空":
            texts.append(title[:72])
    blob = " ".join(texts)
    for kw in _MARKET_RISK_KW:
        if kw in blob:
            risks.append(f"大盘事件：**{kw}** 相关利空")
    for row in featured:
        title = str(row.get("title") or "")
        if any(k in title for k in _MARKET_RISK_KW):
            risks.append(title[:96])
    if not risks and texts:
        risks.extend(texts[:2])
    return risks[:4]


def _collect_sector_risks(ctx: Any) -> list[str]:
    risks: list[str] = []
    snap = ctx.primary_snapshot or {}
    featured, _extra = select_macro_headlines(
        macro_signals=ctx.macro_signals,
        sources=snap.get("sources"),
        portfolio=ctx.portfolio,
        limit=6,
    )
    for row in featured:
        title = str(row.get("title") or "")
        sectors = str(row.get("sectors") or "")
        if infer_impact_label(title) != "利空":
            continue
        if any(k in title for k in _SECTOR_RISK_KW):
            risks.append(f"**{sectors}** {title[:72]}")
        elif sectors and sectors != "综合":
            risks.append(f"**{sectors}** {title[:72]}")
    return risks[:4]


def render_today_risk_markdown(ctx: Any) -> str:
    from agent_reach.daily_run.close_morning_handoff import render_risk_tracking_markdown

    holding = _collect_holding_risks(ctx)
    market = _collect_market_risks(ctx)
    sector = _collect_sector_risks(ctx)
    tracked = render_risk_tracking_markdown(ctx)
    if not holding and not market and not sector and not tracked:
        return ""

    lines = ["**⚠️ 今日风险**", ""]
    if tracked:
        lines.append("**风险跟踪（昨收→今晨）**")
        lines.extend(tracked)
        lines.append("")
    if holding:
        lines.append("**持仓风险**")
        for item in holding:
            lines.append(f"- {item}")
        lines.append("")
    if market:
        lines.append("**大盘风险**")
        for item in market:
            lines.append(f"- {item}")
        lines.append("")
    if sector:
        lines.append("**板块风险**")
        for item in sector:
            lines.append(f"- {item}")

    time_md = render_time_nodes_markdown(collect_time_nodes(ctx))
    if time_md and not build_action_checklist_rows(ctx):
        lines.extend(["", time_md])
    return "\n".join(lines).strip()


def _prediction_text_from_baseline(baseline: dict[str, Any]) -> str:
    for key in ("morning_prediction", "reasoning", "outlook"):
        text = str(baseline.get(key) or "").strip()
        if text:
            return text[:48]
    verdict = str(baseline.get("verdict") or "")
    if verdict == "回避":
        return "偏弱或继续承压"
    if verdict == "可做":
        return "企稳或延续强势"
    return "震荡观察"


def _describe_actual_move(holding: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, Optional[float]]:
    prev = _prev_close_value(holding, snapshot)
    open_px = _optional_float(holding.get("open") or snapshot.get("open"))
    price = _optional_float(holding.get("price") or snapshot.get("price"))
    current = price if price is not None and price > 0 else open_px
    if prev is None or prev <= 0 or current is None:
        return "数据不足", None
    open_gap = None
    if open_px is not None and open_px > 0:
        open_gap = (open_px - prev) / prev * 100.0
    current_pct = (current - prev) / prev * 100.0
    parts: list[str] = []
    if open_gap is not None:
        parts.append(f"{'高开' if open_gap > 0.15 else '低开' if open_gap < -0.15 else '平开'} {abs(open_gap):.1f}%")
    parts.append(f"当前 {current_pct:+.1f}%")
    return "，".join(parts), current_pct


def _prediction_hit(prediction: str, holding: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    _actual, current_pct = _describe_actual_move(holding, snapshot)
    if current_pct is None:
        return True
    bearish = any(k in prediction for k in ("回落", "承压", "走弱", "减仓", "回避", "下探", "弱"))
    bullish = any(k in prediction for k in ("企稳", "反弹", "突破", "强势", "上行", "冲高"))
    if "冲高回落" in prediction:
        open_px = _optional_float(holding.get("open") or snapshot.get("open"))
        prev = _prev_close_value(holding, snapshot)
        if open_px and prev and prev > 0:
            open_gap = (open_px - prev) / prev * 100.0
            return open_gap > 0.3 and current_pct < open_gap * 0.5
        return current_pct <= 0
    if bearish and not bullish:
        return current_pct <= 0.5
    if bullish and not bearish:
        return current_pct >= -0.5
    if "震荡" in prediction or "观察" in prediction:
        return abs(current_pct) <= 2.0
    return True


def build_yesterday_prediction_lines(ctx: Any, *, limit: int = 2) -> list[str]:
    from agent_reach.daily_run.prior_close import load_close_baseline, prev_trading_day
    from agent_reach.daily_run.trade_calendar import today_shanghai

    yday = prev_trading_day(today_shanghai(), settings=ctx.settings)
    lines: list[str] = []
    for sym in ctx.symbol_rows:
        if int((sym.holding or {}).get("shares") or 0) <= 0:
            continue
        code = _normalize_code(sym.code)
        baseline = load_close_baseline(code, target_day=yday, settings=ctx.settings)
        if not baseline:
            continue
        prediction = _prediction_text_from_baseline(baseline)
        actual, _pct = _describe_actual_move(sym.holding or {}, sym.snapshot or {})
        hit = _prediction_hit(prediction, sym.holding or {}, sym.snapshot or {})
        mark = "✅" if hit else "❌"
        lines.append(f"- 昨日预测「{sym.name} {prediction}」→ {mark} 实际{actual}")
        if len(lines) >= limit:
            break
    return lines


def render_yesterday_prediction_validation_markdown(ctx: Any) -> str:
    from agent_reach.daily_run.close_morning_handoff import render_yesterday_focus_validation_markdown

    focus_md = render_yesterday_focus_validation_markdown(ctx)
    if focus_md.strip():
        return focus_md

    lines = build_yesterday_prediction_lines(ctx, limit=2)
    if not lines:
        return ""
    return "**昨日预测验证**\n\n" + "\n".join(lines)


def render_holdings_overview_markdown(ctx: Any) -> str:
    from agent_reach.daily_run.global_markets_collector import render_global_markets_markdown
    from agent_reach.daily_run.morning_content_scope import (
        render_domestic_market_brief,
        render_macro_headlines_markdown,
        render_prior_close_recap_markdown,
        select_macro_headlines,
    )

    lines: list[str] = []
    snap = ctx.primary_snapshot or {}

    recap_md = render_prior_close_recap_markdown(ctx.portfolio, settings=ctx.settings)
    if recap_md.strip():
        lines.append(recap_md)
        lines.append("")

    pred_md = render_yesterday_prediction_validation_markdown(ctx)
    if pred_md.strip():
        lines.append(pred_md)
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

    table_md = render_holdings_snapshot_table_markdown(ctx)
    if table_md.strip():
        lines.append(table_md)
    return "\n".join(lines).strip()
