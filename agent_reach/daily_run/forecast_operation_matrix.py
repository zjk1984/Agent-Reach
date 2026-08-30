# -*- coding: utf-8
"""Sunday forecast operation matrix — master plan, scenarios, timeline, guidance."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from agent_reach.daily_run.forecast_quality import position_hint_for_confidence
from agent_reach.daily_run.snapshot_builder import _normalize_code

_VALID_OPS = frozenset({"加仓", "减仓", "持有", "新建仓", "清仓"})


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: float, *, signed: bool = True) -> str:
    if signed:
        return f"{value:+.1f}%"
    return f"{value:.1f}%"


def _weight_pct(holding: dict[str, Any], total: Optional[float]) -> float:
    mv = _optional_float(holding.get("market_value"))
    if mv is None or not total:
        return 0.0
    return round(mv / float(total) * 100.0, 1)


def _load_stop_loss(code: str, *, settings: Optional[dict[str, Any]] = None) -> Optional[float]:
    try:
        from agent_reach.daily_run.prior_close import load_close_baseline, prev_trading_day

        baseline = load_close_baseline(code, target_day=prev_trading_day(settings=settings), settings=settings)
        return _optional_float((baseline or {}).get("stop_loss_price"))
    except Exception:
        return None


def _resolve_operation_type(
    *,
    outlook_action: str,
    confidence_pct: float,
    position_hint: str,
) -> str:
    action = str(outlook_action or "").strip()
    if action in _VALID_OPS:
        return action
    if "清仓" in action or "止损" in action and confidence_pct < 50:
        return "清仓"
    if "减仓" in action or confidence_pct < 55 or "观望" in position_hint:
        return "减仓"
    if "新建" in action:
        return "新建仓"
    if "加仓" in action or "买入" in action:
        return "加仓"
    return "持有"


def _target_weight_display(
    current: float,
    operation: str,
    *,
    confidence_pct: float,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    fc = (settings or {}).get("finance_close") or {}
    max_pos = float(fc.get("max_position_pct") or 20)
    if operation == "加仓":
        delta = 10 if confidence_pct >= 80 else 5 if confidence_pct >= 60 else 3
        target = min(current + delta, max_pos)
        return f"{current:.0f}%→{target:.0f}%"
    if operation == "减仓":
        target = max(current * 0.6, 5.0)
        return f"{current:.0f}%→{target:.0f}%"
    if operation == "清仓":
        return f"{current:.0f}%→0%"
    if operation == "新建仓":
        init = min(10.0, max_pos)
        return f"0%→{init:.0f}%"
    return f"维持{current:.0f}%"


def _trigger_for_operation(
    operation: str,
    *,
    pred: dict[str, Any],
    outlook_row: dict[str, Any],
) -> str:
    outlook_trigger = str(outlook_row.get("trigger") or "").strip()
    if outlook_trigger and outlook_trigger != "—":
        return outlook_trigger[:40]
    low = _optional_float(pred.get("price_low"))
    mid = _optional_float(pred.get("price_mid"))
    high = _optional_float(pred.get("price_high"))
    if operation == "加仓" and mid:
        return f"回调至{round(mid * 0.95):.0f}元"
    if operation == "减仓" and high:
        return f"反弹至{high:.0f}元"
    if operation == "新建仓" and mid:
        return f"回调至{round(mid * 0.95):.0f}元"
    if operation == "清仓" and low:
        return f"跌破{round(low * 0.98):.0f}元"
    return "—"


def _stop_display(
    code: str,
    operation: str,
    *,
    pred: dict[str, Any],
    outlook_row: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> str:
    outlook_stop = str(outlook_row.get("stop_loss") or "").strip()
    if outlook_stop and outlook_stop != "—":
        return outlook_stop.replace(" 元", "元")[:16]
    low = _optional_float(pred.get("price_low"))
    if low:
        return f"{round(low * 0.98):.0f}元"
    stop = _load_stop_loss(code, settings=settings)
    if stop:
        return f"{stop:.2f}元"
    if operation in ("加仓", "新建仓", "持有"):
        return "—"
    return "—"


def build_master_operation_rows(
    *,
    portfolio: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    outlook: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    pf = portfolio or {}
    total = _optional_float(pf.get("total_value") or pf.get("portfolio_total"))
    sym_preds = {
        _normalize_code(str(s.get("code") or "")): s
        for s in (structured or {}).get("symbols") or []
        if s.get("code")
    }
    outlook_map = {
        _normalize_code(str(r.get("code") or "")): r
        for r in (outlook or {}).get("operation_plan") or []
        if r.get("code")
    }
    held_codes: set[str] = set()
    rows: list[dict[str, Any]] = []

    for h in pf.get("holdings") or []:
        code = _normalize_code(str(h.get("code") or ""))
        if not code:
            continue
        held_codes.add(code)
        pred = sym_preds.get(code) or {}
        outlook_row = outlook_map.get(code) or {}
        cur = _weight_pct(h, total)
        conf = _optional_float(pred.get("confidence_pct")) or 60.0
        pos_hint = str(pred.get("position_hint") or position_hint_for_confidence(conf))
        op = _resolve_operation_type(
            outlook_action=str(outlook_row.get("action") or ""),
            confidence_pct=conf,
            position_hint=pos_hint,
        )
        rows.append(
            {
                "code": code,
                "name": h.get("name") or pred.get("name") or code,
                "current_weight_pct": cur,
                "operation": op,
                "trigger": _trigger_for_operation(op, pred=pred, outlook_row=outlook_row),
                "target_weight": _target_weight_display(
                    cur, op, confidence_pct=conf, settings=settings
                ),
                "stop_loss": _stop_display(
                    code, op, pred=pred, outlook_row=outlook_row, settings=settings
                ),
            }
        )

    for item in (outlook or {}).get("operation_plan") or []:
        code = _normalize_code(str(item.get("code") or ""))
        if not code or code in held_codes:
            continue
        action = str(item.get("action") or "")
        if action not in ("买入", "新建仓"):
            continue
        pred = sym_preds.get(code) or {}
        conf = _optional_float(pred.get("confidence_pct")) or 55.0
        op = "新建仓"
        rows.append(
            {
                "code": code,
                "name": item.get("name") or code,
                "current_weight_pct": 0.0,
                "operation": op,
                "trigger": _trigger_for_operation(op, pred=pred, outlook_row=item),
                "target_weight": _target_weight_display(0.0, op, confidence_pct=conf, settings=settings),
                "stop_loss": _stop_display(code, op, pred=pred, outlook_row=item, settings=settings),
            }
        )

    stock_w = sum(float(r.get("current_weight_pct") or 0) for r in rows)
    cash = max(0.0, round(100.0 - stock_w, 1))
    rows.append(
        {
            "code": "CASH",
            "name": "现金",
            "current_weight_pct": cash,
            "operation": "—",
            "trigger": "—",
            "target_weight": "—",
            "stop_loss": "—",
        }
    )
    return rows


def build_position_guidance(
    *,
    portfolio: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    timeline: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    pf = portfolio or {}
    total = _optional_float(pf.get("total_value") or pf.get("portfolio_total"))
    current_stock = sum(_weight_pct(h, total) for h in pf.get("holdings") or [])
    current_cash = max(0.0, round(100.0 - current_stock, 1))
    market = (structured or {}).get("market") or {}
    conf = _optional_float(market.get("confidence_pct")) or 65.0
    high_events = sum(1 for e in timeline or [] if str(e.get("severity_emoji")) == "🔴")
    med_events = sum(1 for e in timeline or [] if str(e.get("severity_emoji")) == "🟡")

    fc = (settings or {}).get("finance_close") or {}
    max_single = int(fc.get("max_position_pct") or 20)

    if high_events >= 1 or conf < 60:
        target_lo, target_hi = max(45, current_stock - 15), max(50, current_stock - 10)
        rationale = "下周有重大事件/预测置信度偏低，建议中等偏低仓位"
    elif med_events >= 2:
        target_lo, target_hi = max(50, current_stock - 10), current_stock
        rationale = "下周事件较多，建议略降仓位"
    else:
        target_lo, target_hi = max(50, current_stock - 5), min(80, current_stock + 5)
        rationale = "基准情景下维持中性仓位"

    cash_lo = max(20, round(100 - target_hi, 0))
    cash_hi = min(60, round(100 - target_lo, 0))
    adjust = ""
    mid_target = (target_lo + target_hi) / 2
    if mid_target < current_stock - 3:
        adjust = f"整体仓位从{current_stock:.0f}%降至{mid_target:.0f}%（约减{current_stock - mid_target:.0f}%）"
    elif mid_target > current_stock + 3:
        adjust = f"整体仓位从{current_stock:.0f}%升至{mid_target:.0f}%（约加{mid_target - current_stock:.0f}%）"

    return {
        "current_stock_pct": round(current_stock, 1),
        "current_cash_pct": round(current_cash, 1),
        "target_stock_range": (target_lo, target_hi),
        "target_cash_range": (cash_lo, cash_hi),
        "max_single_pct": max_single,
        "max_sector_pct": 50,
        "rationale": rationale,
        "adjustment": adjust,
        "summary": (
            f"下周建议整体仓位：{target_lo:.0f}%-{target_hi:.0f}%（当前{current_stock:.0f}%），"
            f"现金比例{cash_lo:.0f}%-{cash_hi:.0f}%"
        ),
        "concentration": f"单只股票不超过{max_single}%，科技链合计不超过50%",
    }


def build_scenario_plans(
    *,
    structured: Optional[dict[str, Any]] = None,
    master_rows: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    market = (structured or {}).get("market") or {}
    lo = float(market.get("change_pct_low") or -0.5)
    hi = float(market.get("change_pct_high") or 1.0)
    mid = float(market.get("change_pct_mid") or (lo + hi) / 2)

    add_example = "按操作总表执行"
    for row in master_rows or []:
        if row.get("operation") == "加仓" and row.get("trigger") not in ("—", None):
            add_example = f"按操作总表执行，{row.get('name')}{row.get('trigger')}加仓"
            break

    risk_floor = round(min(lo, mid) - 2.0, 1)
    optimistic_cap = round(max(hi, mid) + 1.0, 1)

    return [
        {
            "name": "基准：震荡上行",
            "probability_pct": 60,
            "trigger": f"沪深300在 {_fmt_pct(lo)}~{_fmt_pct(hi)}",
            "response": add_example,
        },
        {
            "name": "风险：大幅下跌",
            "probability_pct": 25,
            "trigger": f"沪深300跌破 {_fmt_pct(risk_floor)}",
            "response": "全面减仓至40%左右，优先减仓高beta/低置信度个股",
        },
        {
            "name": "乐观：大幅上涨",
            "probability_pct": 15,
            "trigger": f"沪深300突破 {_fmt_pct(optimistic_cap)}",
            "response": "持有不追高，等待回调再按加仓触发执行",
        },
    ]


def _severity_emoji(severity: str) -> str:
    s = str(severity or "")
    if s in ("高", "HIGH", "high"):
        return "🔴"
    if s in ("低", "LOW", "low", "🟢"):
        return "🟢"
    return "🟡"


def _timeline_response(event: str, scope: str, severity: str) -> str:
    if _severity_emoji(severity) == "🔴":
        if scope == "大盘波动" or "CPI" in event or "美联储" in event:
            return "事件前降低仓位至50%，避免新开仓"
        return "事件前相关持仓减半，收紧止损"
    if "财报" in event or "披露" in event:
        return "财报前减仓至10%，公布后按结果调整"
    if scope == "大盘波动" or "交割" in event:
        return "交割日避免开新仓，控制总仓位"
    return "相关持仓减半；止损收紧至-5%"


def build_key_timeline(
    *,
    risk_calendar: Optional[list[dict[str, Any]]] = None,
    watchlist_intel: Optional[dict[str, Any]] = None,
    portfolio: Optional[dict[str, Any]] = None,
    week_start: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    held_names = {
        str(h.get("name") or "") for h in (portfolio or {}).get("holdings") or []
    }

    for item in risk_calendar or []:
        event = str(item.get("event") or "")
        scope = str(item.get("scope") or "—")
        if scope not in ("大盘波动", "组合", "持仓", "个股") and scope != "—":
            if not any(n in event for n in held_names if n):
                continue
        sev = str(item.get("severity") or "中")
        rows.append(
            {
                "date": str(item.get("date") or "")[:10],
                "event": event,
                "scope": scope,
                "severity": sev,
                "severity_emoji": _severity_emoji(sev),
                "response": _timeline_response(event, scope, sev),
            }
        )

    for code, block in (watchlist_intel or {}).items():
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or code)
        if name not in held_names and code not in {
            _normalize_code(str(h.get("code") or "")) for h in (portfolio or {}).get("holdings") or []
        }:
            continue
        for ann in (block.get("announcements") or [])[:1]:
            title = str(ann.get("title") or "")[:30]
            pub = str(ann.get("date") or ann.get("pub_date") or "")[:10]
            if not title:
                continue
            rows.append(
                {
                    "date": pub or week_start or "",
                    "event": f"{name} {title}",
                    "scope": "个股",
                    "severity": "中",
                    "severity_emoji": "🟡",
                    "response": "财报/公告前减仓至10%，公布后按结果调整",
                }
            )

    rows.sort(key=lambda r: str(r.get("date") or ""))
    return rows[:6]


def build_limitations_statement(
    *,
    structured: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    high_unc: list[str] = []
    for sym in (structured or {}).get("symbols") or []:
        conf = _optional_float(sym.get("confidence_pct"))
        factors = " ".join(str(x) for x in (sym.get("evidence") or []))
        if (conf is not None and conf < 60) or "不确定性" in factors or "公告" in factors:
            high_unc.append(str(sym.get("name") or sym.get("code")))
    lines = [
        "本预测基于当前可获取的数据和模型输出，不构成投资建议。",
        "市场存在不可预测的黑天鹅事件，预测可能与实际走势存在重大偏差。",
        "请严格执行止损与仓位上限，预测错误时按情景预案应对。",
    ]
    return {
        "lines": lines,
        "high_uncertainty_names": high_unc[:4],
    }


def build_forecast_operation_matrix(
    *,
    portfolio: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    outlook: Optional[dict[str, Any]] = None,
    forecast: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    fc = forecast or {}
    intel = fc.get("watchlist_intel") or {}
    risks = list((outlook or {}).get("risk_calendar") or fc.get("risk_calendar") or [])
    master_rows = build_master_operation_rows(
        portfolio=portfolio,
        structured=structured,
        outlook=outlook,
        settings=settings,
    )
    timeline = build_key_timeline(
        risk_calendar=risks,
        watchlist_intel=intel,
        portfolio=portfolio,
        week_start=str(fc.get("week_start") or ""),
    )
    guidance = build_position_guidance(
        portfolio=portfolio,
        structured=structured,
        timeline=timeline,
        settings=settings,
    )
    scenarios = build_scenario_plans(structured=structured, master_rows=master_rows)
    limitations = build_limitations_statement(structured=structured)
    return {
        "master_rows": master_rows,
        "position_guidance": guidance,
        "scenarios": scenarios,
        "timeline": timeline,
        "limitations": limitations,
    }


def render_master_operation_markdown(matrix: dict[str, Any]) -> str:
    guidance = matrix.get("position_guidance") or {}
    rows = matrix.get("master_rows") or []
    lines = ["## 📋 下周操作计划总表", ""]
    if guidance.get("summary"):
        lines.append(f"**整体仓位：** {guidance['summary']}")
    if guidance.get("concentration"):
        lines.append(f"**集中度：** {guidance['concentration']}")
    if guidance.get("rationale"):
        lines.append(f"**依据：** {guidance['rationale']}")
    if guidance.get("adjustment"):
        lines.append(f"**调整：** {guidance['adjustment']}")
    lines.append("")
    lines.extend(
        [
            "| 股票 | 当前仓位 | 下周操作 | 触发条件 | 目标仓位 | 止损位 |",
            "|------|---------|----------|----------|---------|--------|",
        ]
    )
    for row in rows:
        cur = row.get("name") if row.get("code") == "CASH" else row.get("name")
        w = (
            f"{float(row.get('current_weight_pct') or 0):.0f}%"
            if row.get("code") != "CASH"
            else f"{float(row.get('current_weight_pct') or 0):.0f}%"
        )
        lines.append(
            f"| {cur} | {w} | {row.get('operation')} | {row.get('trigger')} | "
            f"{row.get('target_weight')} | {row.get('stop_loss')} |"
        )
    lines.append("")
    lines.append("_无止损位的加仓/新建仓建议暂不执行；预测错误时见「情景预案」卡。_")
    return "\n".join(lines).strip()


def render_scenario_markdown(matrix: dict[str, Any]) -> str:
    scenarios = matrix.get("scenarios") or []
    lines = ["## 🔀 情景预案（预测错误怎么办）", ""]
    lines.extend(
        [
            "| 情景 | 概率 | 触发条件 | 操作应对 |",
            "|------|------|----------|----------|",
        ]
    )
    for row in scenarios:
        lines.append(
            f"| {row.get('name')} | {int(row.get('probability_pct') or 0)}% | "
            f"{row.get('trigger')} | {row.get('response')} |"
        )
    return "\n".join(lines).strip()


def render_timeline_markdown(matrix: dict[str, Any]) -> str:
    rows = matrix.get("timeline") or []
    lines = ["## 📅 下周关键时间节点", ""]
    if not rows:
        lines.append("- 暂无与持仓/大盘直接相关的重大事件登记")
        return "\n".join(lines).strip()
    lines.extend(
        [
            "| 日期 | 事件 | 影响范围 | 严重程度 | 应对建议 |",
            "|------|------|----------|:--------:|----------|",
        ]
    )
    for row in rows:
        ds = str(row.get("date") or "")
        label = ds[5:] if len(ds) >= 10 else ds
        lines.append(
            f"| {label} | {row.get('event')} | {row.get('scope')} | "
            f"{row.get('severity_emoji')} | {row.get('response')} |"
        )
    return "\n".join(lines).strip()


def render_limitations_markdown(matrix: dict[str, Any]) -> str:
    block = matrix.get("limitations") or {}
    lines = ["## ⚠️ 预测局限性", ""]
    for sentence in (block.get("lines") or [])[:3]:
        lines.append(f"- {sentence}")
    names = block.get("high_uncertainty_names") or []
    if names:
        lines.append(f"- **高不确定性：** {'、'.join(names)}（财报/公告前，建议轻仓）")
    return "\n".join(lines).strip()
