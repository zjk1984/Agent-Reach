# -*- coding: utf-8
"""Midday Feishu cards — half-day verify + afternoon plan (3–4 cards, no close-style depth)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.report_push import ReportSection
from agent_reach.daily_run.snapshot_builder import _normalize_code

MIDDAY_DATA_CUTOFF = "截至 11:30 收盘"
_SHANGHAI = ZoneInfo("Asia/Shanghai")

MIDDAY_CARD_ORDER: tuple[str, ...] = (
    "plan_verify",
    "session_brief",
    "afternoon_risk",
)

MIDDAY_CARD_LABELS: dict[str, str] = {
    "plan_verify": "📋 早盘验证 · 下午展望",
    "session_brief": "☀️ 上午盘面要点",
    "afternoon_risk": "⚠️ 个股风险",
}


def midday_card_layout_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = (settings or {}).get("report") or {}
    layout = str(cfg.get("midday_card_layout", "cards")).lower()
    return layout not in ("legacy", "old", "false", "0")


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class MiddayCardContext:
    plan_rows: list[dict[str, Any]] = field(default_factory=list)
    plan_unchanged: bool = True
    session_brief: dict[str, Any] = field(default_factory=dict)
    risk_lines: list[str] = field(default_factory=list)
    audit_banner: str = ""
    data_as_of: str = MIDDAY_DATA_CUTOFF
    data_quality_notes: list[str] = field(default_factory=list)
    morning_diverged: bool = False
    morning_diverged_note: str = ""
    market_key_points: list[str] = field(default_factory=list)
    macro_impact_line: str = ""
    morning_reference: str = ""
    settings: Optional[dict[str, Any]] = None


def _morning_plan_text(action: dict[str, Any]) -> str:
    trigger = str(action.get("trigger") or "").strip()
    operation = str(action.get("operation") or "").strip()
    target = str(action.get("target_position") or "").strip()
    if trigger and trigger != "—":
        if operation and operation not in trigger:
            return f"{operation} · {trigger}"
        return trigger
    if target:
        return f"{operation} · {target}" if operation else target
    return operation or "—"


def _scan_num(scan_id: object) -> Optional[int]:
    raw = str(scan_id or "").strip().upper()
    if raw.startswith("S") and raw[1:].isdigit():
        return int(raw[1:])
    return None


def _am_scans(state: dict[str, Any]) -> list[dict[str, Any]]:
    scans = list(state.get("scans") or [])
    am: list[dict[str, Any]] = []
    for scan in scans:
        src = str(scan.get("source") or "")
        sid = _scan_num(scan.get("scan_id"))
        if src == "midday":
            continue
        if sid is not None and sid <= 7:
            am.append(scan)
        elif src in {"morning", ""}:
            am.append(scan)
    return am or scans[:-1] if len(scans) > 1 else scans


def _holding_for_code(enriched: dict[str, Any], code: str) -> dict[str, Any]:
    pf = enriched.get("portfolio") or {}
    for row in pf.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) == code:
            return dict(row)
    return {}


def _snapshot_fields(enriched: dict[str, Any], code: str) -> dict[str, Any]:
    if _normalize_code(str(enriched.get("code") or "")) == code:
        return dict(enriched)
    return {}


def _session_price_stats(
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    am_scans: list[dict[str, Any]],
) -> dict[str, Optional[float]]:
    prices: list[float] = []
    for key in ("open", "price", "high", "low"):
        val = _optional_float(holding.get(key) if key in holding else snapshot.get(key))
        if val is not None and val > 0:
            prices.append(val)
    for scan in am_scans:
        px = _optional_float(scan.get("price"))
        if px is not None and px > 0:
            prices.append(px)
    open_px = _optional_float(holding.get("open") or snapshot.get("open"))
    price = _optional_float(holding.get("price") or snapshot.get("price"))
    high = max(prices) if prices else None
    low = min(prices) if prices else None
    return {"open": open_px, "price": price, "high": high, "low": low}


def _change_pct(holding: dict[str, Any], snapshot: dict[str, Any]) -> Optional[float]:
    from agent_reach.daily_run.close_morning_handoff import _describe_actual_move

    _text, pct = _describe_actual_move(holding, snapshot)
    return pct


def _parse_level_from_text(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?", str(text or ""))
    if match:
        return float(match.group(1))
    return None


def _is_before_noon_shanghai(at_iso: str) -> bool:
    raw = str(at_iso or "").strip()
    if not raw:
        return True
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(_SHANGHAI)
        return local.hour < 12
    except ValueError:
        return True


def _fills_from_trade_record(trade: dict[str, Any]) -> list[dict[str, Any]]:
    fills: list[dict[str, Any]] = []
    at = str(trade.get("as_of") or "")
    for action in trade.get("portfolio_actions") or []:
        if action.get("side") not in ("buy", "sell"):
            continue
        fills.append(
            {
                "side": action.get("side"),
                "code": _normalize_code(str(action.get("code") or trade.get("code") or "")),
                "price": _optional_float(action.get("price")),
                "shares": int(action.get("shares") or 0),
                "at": at,
            }
        )
    if fills:
        return fills
    side = str(trade.get("action") or "")
    if side in ("buy", "sell"):
        fills.append(
            {
                "side": side,
                "code": _normalize_code(str(trade.get("code") or "")),
                "price": _optional_float(trade.get("price")),
                "shares": int(trade.get("shares") or 0),
                "at": at,
            }
        )
    return fills


def _collect_am_trades_by_code(
    *,
    state: dict[str, Any],
    day: date,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, list[dict[str, Any]]]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str, int, float]] = set()

    def _append(fill: dict[str, Any]) -> None:
        code = _normalize_code(str(fill.get("code") or ""))
        if not code:
            return
        at = str(fill.get("at") or "")
        if not _is_before_noon_shanghai(at):
            return
        side = str(fill.get("side") or "")
        shares = int(fill.get("shares") or 0)
        price = _optional_float(fill.get("price"))
        key = (code, side, at, shares, float(price or 0))
        if key in seen:
            return
        seen.add(key)
        by_code[code].append(fill)

    for trade in state.get("trades") or []:
        if not isinstance(trade, dict):
            continue
        if trade.get("portfolio_applied") is False:
            continue
        for fill in _fills_from_trade_record(trade):
            _append(fill)

    try:
        from agent_reach.daily_run.realized_pnl import load_ledger_entries

        for entry in load_ledger_entries(start=day, end=day, settings=settings):
            if entry.get("portfolio_applied") is False:
                continue
            at = str(entry.get("at") or "")
            if not _is_before_noon_shanghai(at):
                continue
            for action in entry.get("actions") or []:
                if action.get("side") not in ("buy", "sell"):
                    continue
                _append(
                    {
                        "side": action.get("side"),
                        "code": action.get("code"),
                        "price": action.get("price"),
                        "shares": action.get("shares"),
                        "at": at,
                    }
                )
    except Exception:
        pass

    return dict(by_code)


def _avg_fill_price(fills: list[dict[str, Any]]) -> Optional[float]:
    total_shares = 0
    total_amount = 0.0
    for fill in fills:
        shares = int(fill.get("shares") or 0)
        price = _optional_float(fill.get("price"))
        if shares <= 0 or price is None:
            continue
        total_shares += shares
        total_amount += shares * price
    if total_shares <= 0:
        return None
    return round(total_amount / total_shares, 2)


def _relevant_fills(
    fills: list[dict[str, Any]],
    *,
    operation: str,
) -> list[dict[str, Any]]:
    if operation == "减仓":
        return [f for f in fills if f.get("side") == "sell"]
    if operation == "加仓":
        return [f for f in fills if f.get("side") == "buy"]
    return fills


def _price_trigger_touched(
    *,
    operation: str,
    trigger: str,
    stats: dict[str, Optional[float]],
) -> bool:
    level = _parse_level_from_text(trigger)
    if level is None:
        return False
    low = stats.get("low")
    high = stats.get("high")
    trig = str(trigger or "")
    if "跌破" in trig or "≤" in trig or (operation == "减仓" and level is not None):
        return low is not None and low <= level
    if "突破" in trig or "≥" in trig or (operation == "加仓" and level is not None):
        return high is not None and high >= level
    return False


def _validate_trigger_level(
    *,
    operation: str,
    trigger: str,
    stats: dict[str, Optional[float]],
) -> tuple[bool, Optional[str]]:
    """Return (am_session_triggered, trigger_warning)."""
    level = _parse_level_from_text(trigger)
    price = stats.get("price")
    if level is None:
        return False, None

    am_triggered = _price_trigger_touched(operation=operation, trigger=trigger, stats=stats)
    warning: Optional[str] = None
    if price is not None and price > 0:
        if operation == "减仓" or "跌破" in trigger:
            if level > price * 1.01:
                warning = "⚠️ 价位待确认"
        elif operation == "加仓" or "突破" in trigger:
            if level < price * 0.99:
                warning = "⚠️ 价位待确认"
    return am_triggered, warning


def _format_am_actual(
    *,
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    stats: dict[str, Optional[float]],
    change_pct: Optional[float],
) -> tuple[str, bool]:
    """Return (display_text, data_stale)."""
    vol = _optional_float(holding.get("volume_ratio") or snapshot.get("volume_ratio"))
    price = stats.get("price")
    if change_pct is None or vol is None or price is None:
        return "⚠️ 数据更新中", True
    return f"{change_pct:+.1f}% · 量比{vol:.1f}x", False


def _format_position_change(
    *,
    morning_weight: Optional[float],
    am_weight: Optional[float],
) -> str:
    if morning_weight is None and am_weight is None:
        return ""
    if morning_weight is not None and am_weight is not None:
        if abs(morning_weight - am_weight) >= 0.4:
            return f"{MIDDAY_DATA_CUTOFF} · 早盘 {morning_weight:.0f}% → 上午收盘 {am_weight:.0f}%"
        return f"{MIDDAY_DATA_CUTOFF} · 维持 {am_weight:.0f}%"
    if am_weight is not None:
        return f"{MIDDAY_DATA_CUTOFF} · 上午收盘 {am_weight:.0f}%"
    return MIDDAY_DATA_CUTOFF


def _verify_plan(
    *,
    morning_plan: str,
    operation: str,
    trigger: str,
    stats: dict[str, Optional[float]],
    change_pct: Optional[float],
    am_fills: list[dict[str, Any]],
    morning_current: Optional[float],
    morning_target: Optional[float],
    am_weight: Optional[float],
    data_stale: bool,
) -> tuple[str, str, str, str, bool, bool, Optional[str], bool]:
    """Return verify fields + flags for afternoon planning."""
    from agent_reach.daily_run.close_morning_handoff import _action_executed

    plan_lower = morning_plan.lower()
    am_triggered, trigger_warning = _validate_trigger_level(
        operation=operation,
        trigger=trigger,
        stats=stats,
    )
    price_touched = _price_trigger_touched(operation=operation, trigger=trigger, stats=stats)
    relevant = _relevant_fills(am_fills, operation=operation)
    avg_px = _avg_fill_price(relevant)
    filled = bool(relevant)

    if data_stale:
        return "—", "—", "数据更新中", "行情缺失", False, False, trigger_warning, am_triggered

    weight_executed = False
    if am_weight is not None:
        weight_executed = _action_executed(
            operation=operation,
            morning_current=morning_current,
            morning_target=morning_target,
            actual_weight=am_weight,
        )

    if filled and avg_px is not None:
        side = "卖出" if relevant[0].get("side") == "sell" else "买入"
        verify = f"✅ 已成交，{side}均价 {avg_px:.2f} 元"
        return verify, "✅", "已成交", "成交记录", True, price_touched, trigger_warning, am_triggered

    if weight_executed and operation in ("减仓", "加仓"):
        target_s = f"{morning_target:.0f}%" if morning_target is not None else "目标"
        verify = f"✅ 仓位已调整至 {am_weight:.1f}%（{target_s}）"
        return verify, "✅", "已执行", "上午收盘仓位", True, price_touched, trigger_warning, am_triggered

    if price_touched and not filled and operation in ("减仓", "加仓"):
        touch = "最低价" if operation == "减仓" else "最高价"
        px = stats.get("low") if operation == "减仓" else stats.get("high")
        px_s = f"{px:.2f}" if px is not None else "—"
        verify = f"⚠️ 价格触及（{touch} {px_s}），未成交"
        return verify, "⚠️", "触及未成交", "价格扫描", False, True, trigger_warning, am_triggered

    if operation in ("观望", "持有") or "观望" in plan_lower:
        if change_pct is not None:
            if change_pct >= 1.0 and stats.get("open") is not None and stats.get("price") is not None:
                open_px = stats.get("open")
                price = stats.get("price")
                if open_px is not None and price is not None and price > open_px:
                    return (
                        "⚠️ 超预期",
                        "⚠️",
                        "超预期",
                        "上午行情",
                        False,
                        False,
                        trigger_warning,
                        am_triggered,
                    )
            if change_pct <= -1.0:
                return (
                    "⚠️ 偏弱",
                    "⚠️",
                    "偏弱",
                    "上午行情",
                    False,
                    False,
                    trigger_warning,
                    am_triggered,
                )
            return (
                "✅ 符合预期",
                "✅",
                "符合预期",
                "上午行情",
                False,
                False,
                trigger_warning,
                am_triggered,
            )
        return "—", "—", "待确认", "数据不足", False, False, trigger_warning, am_triggered

    if am_triggered:
        return "❌ 已触发，未成交", "❌", "未成交", "价格扫描", False, True, trigger_warning, True

    if change_pct is not None:
        return (
            "❌ 未触发",
            "❌",
            "未触发",
            "价格扫描",
            False,
            False,
            trigger_warning,
            am_triggered,
        )
    return "—", "—", "待确认", "数据不足", False, False, trigger_warning, am_triggered


def _afternoon_action(
    *,
    morning_plan: str,
    operation: str,
    trigger: str,
    verify_icon: str,
    verify_label: str,
    target_weight: Optional[float],
    current_weight: Optional[float],
    am_weight: Optional[float],
    stats: dict[str, Optional[float]],
    changed: bool,
    am_triggered: bool,
    filled: bool,
    trigger_warning: Optional[str],
    morning_diverged: bool,
    data_stale: bool,
    position_change: str,
) -> tuple[str, bool]:
    """Return (afternoon_action_markdown, is_changed)."""
    from agent_reach.daily_run.midday_content_scope import MIDDAY_PLAN_UNCHANGED

    target_s = f"{target_weight:.0f}%" if target_weight is not None else "原目标"
    stop = _parse_level_from_text(trigger)
    price = stats.get("price")

    if data_stale:
        return "⚠️ 待行情更新", False

    if trigger_warning:
        if am_triggered:
            return f"上午已触发 · {trigger_warning}，下午复核价位", True
        return f"{trigger_warning}，下午复核触发价", True

    if am_triggered and filled:
        rebound = stats.get("high") or stats.get("price")
        if operation == "减仓" and rebound is not None:
            return f"已成交，反弹至 **{rebound:.1f}** 可继续减", True
        if operation == "加仓":
            return "已成交，下午关注趋势延续", True
        return MIDDAY_PLAN_UNCHANGED, False

    if am_triggered and not filled:
        if operation == "减仓":
            return "上午已触发未成交，可下调卖价", True
        if operation == "加仓":
            return "上午已触发未成交，可上调买价", True
        return "上午已触发，下午跟踪", True

    if morning_diverged and verify_label in {"超预期", "偏弱"}:
        rebound = stats.get("high") or stats.get("price")
        if rebound is not None and operation in ("观望", "持有", "减仓"):
            return f"反弹至 **{rebound:.1f}** 减仓", True
        return "下午宜保守", True

    if verify_icon == "✅" and verify_label in {"已成交", "已执行"}:
        return MIDDAY_PLAN_UNCHANGED, False

    if verify_icon == "❌" and verify_label == "未触发":
        if operation == "加仓" and stop is not None:
            stop_loss = round(stop * 0.95, 2) if stop > 1 else stop
            if price is not None and stop_loss >= price:
                return "⚠️ 止损位待确认", True
            return f"跌破 **{stop_loss:.2f}** 止损", False
        return MIDDAY_PLAN_UNCHANGED, False

    if verify_icon == "⚠️" and verify_label == "超预期":
        rebound = stats.get("high") or stats.get("price")
        if rebound is not None:
            return f"反弹至 **{rebound:.1f}** 减仓", True
        return "下午择机减仓", True

    if operation in ("观望", "持有"):
        return MIDDAY_PLAN_UNCHANGED, False

    return MIDDAY_PLAN_UNCHANGED, False


def build_midday_plan_rows(
    *,
    morning_handoff: Optional[dict[str, Any]],
    enriched: dict[str, Any],
    state: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
    day: Optional[date] = None,
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.morning_cards import _holding_weight_pct
    from agent_reach.daily_run.trade_calendar import today_shanghai

    actions = list((morning_handoff or {}).get("action_checklist") or [])
    if not actions:
        return []

    trade_day = day or today_shanghai()
    am_trades = _collect_am_trades_by_code(state=state, day=trade_day, settings=settings)
    portfolio = dict(enriched.get("portfolio") or {})
    am_scans = _am_scans(state)
    rows: list[dict[str, Any]] = []

    for action in actions:
        if not isinstance(action, dict):
            continue
        code = _normalize_code(str(action.get("code") or ""))
        name = str(action.get("name") or code or "—")
        operation = str(action.get("operation") or "")
        trigger = str(action.get("trigger") or "")
        morning_plan = _morning_plan_text(action)
        holding = _holding_for_code(enriched, code)
        snapshot = _snapshot_fields(enriched, code)
        stats = _session_price_stats(holding, snapshot, am_scans)
        change_pct = _change_pct(holding, snapshot)
        target_weight = _optional_float(action.get("target_weight_pct"))
        morning_current = _optional_float(action.get("current_weight_pct"))
        am_weight = _holding_weight_pct(holding, portfolio)
        position_change = _format_position_change(
            morning_weight=morning_current,
            am_weight=am_weight,
        )

        am_actual, data_stale = _format_am_actual(
            holding=holding,
            snapshot=snapshot,
            stats=stats,
            change_pct=change_pct,
        )
        verify, verify_icon, verify_label, verify_source, filled, price_touched, trigger_warning, am_triggered = _verify_plan(
            morning_plan=morning_plan,
            operation=operation,
            trigger=trigger,
            stats=stats,
            change_pct=change_pct,
            am_fills=am_trades.get(code) or [],
            morning_current=morning_current,
            morning_target=target_weight,
            am_weight=am_weight,
            data_stale=data_stale,
        )

        afternoon, changed = _afternoon_action(
            morning_plan=morning_plan,
            operation=operation,
            trigger=trigger,
            verify_icon=verify_icon,
            verify_label=verify_label,
            target_weight=target_weight,
            current_weight=morning_current,
            am_weight=am_weight,
            stats=stats,
            changed=False,
            am_triggered=am_triggered,
            filled=filled,
            trigger_warning=trigger_warning,
            morning_diverged=False,
            data_stale=data_stale,
            position_change=position_change,
        )
        rows.append(
            {
                "code": code,
                "name": name,
                "operation": operation,
                "trigger": trigger,
                "morning_plan": morning_plan,
                "am_actual": am_actual,
                "verify": verify,
                "verify_icon": verify_icon,
                "verify_label": verify_label,
                "verify_source": verify_source,
                "price_touched": price_touched,
                "filled": filled,
                "trigger_warning": trigger_warning,
                "am_triggered": am_triggered,
                "position_change": position_change,
                "morning_weight_pct": morning_current,
                "am_weight_pct": am_weight,
                "afternoon_action": afternoon,
                "changed": changed,
                "data_stale": data_stale,
                "stats": stats,
            }
        )

    morning_diverged = any(r.get("verify_label") in {"超预期", "偏弱"} for r in rows)
    if morning_diverged:
        for row in rows:
            if row.get("verify_label") not in {"超预期", "偏弱"}:
                continue
            afternoon, changed = _afternoon_action(
                morning_plan=str(row.get("morning_plan") or ""),
                operation=str(row.get("operation") or ""),
                trigger=str(row.get("trigger") or ""),
                verify_icon=str(row.get("verify_icon") or ""),
                verify_label=str(row.get("verify_label") or ""),
                target_weight=_optional_float(row.get("morning_weight_pct")),
                current_weight=_optional_float(row.get("morning_weight_pct")),
                am_weight=_optional_float(row.get("am_weight_pct")),
                stats=dict(row.get("stats") or {}),
                changed=False,
                am_triggered=bool(row.get("am_triggered")),
                filled=bool(row.get("filled")),
                trigger_warning=row.get("trigger_warning"),
                morning_diverged=True,
                data_stale=bool(row.get("data_stale")),
                position_change=str(row.get("position_change") or ""),
            )
            row["afternoon_action"] = afternoon
            row["changed"] = bool(row.get("changed")) or changed
    for row in rows:
        row.pop("stats", None)
        row.pop("operation", None)
        row.pop("trigger", None)
    return rows


def build_midday_card_context(
    scan_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    audit: Any = None,
) -> MiddayCardContext:
    from agent_reach.daily_run.close_morning_handoff import load_close_handoff_for_morning, load_morning_handoff
    from agent_reach.daily_run.midday_content_scope import (
        build_am_market_key_points,
        build_holding_risk_lines,
        build_macro_holdings_impact_line,
        build_morning_reference_line,
    )
    from agent_reach.daily_run.trade_calendar import today_shanghai

    enriched = dict(scan_result.get("enriched") or {})
    state = dict(scan_result.get("state") or {})
    scan = dict(scan_result.get("scan") or {})
    morning_handoff = load_morning_handoff(morning_day=today_shanghai())
    close_handoff = load_close_handoff_for_morning(settings=settings)
    portfolio = dict(enriched.get("portfolio") or {})

    plan_rows = build_midday_plan_rows(
        morning_handoff=morning_handoff,
        enriched=enriched,
        state=state,
        settings=settings,
    )
    morning_diverged = any(r.get("verify_label") in {"超预期", "偏弱"} for r in plan_rows)
    plan_unchanged = not plan_rows or (
        not morning_diverged and not any(r.get("changed") for r in plan_rows)
    )
    data_quality_notes: list[str] = []
    if any(r.get("data_stale") for r in plan_rows):
        data_quality_notes.append("部分标的涨跌幅/量比缺失，已标注「⚠️ 数据更新中」")
    morning_diverged_note = ""
    if morning_diverged:
        morning_diverged_note = "**上午实际走势超预期，调整下午预测如下**"

    market_key_points = build_am_market_key_points(enriched, portfolio=portfolio)
    macro_impact_line = build_macro_holdings_impact_line(
        enriched,
        portfolio=portfolio,
        settings=settings,
    )
    morning_reference = build_morning_reference_line(
        morning_handoff,
        close_handoff=close_handoff,
    )

    am_scans = _am_scans(state)
    last_am = am_scans[-1] if am_scans else scan
    session_brief = {
        "last_scan_id": last_am.get("scan_id") or scan.get("reference_scan_id") or "—",
        "mss": last_am.get("mss_final") or scan.get("mss_final"),
        "verdict": last_am.get("verdict") or scan.get("verdict") or "观察",
        "lookback_mss": scan_result.get("lookback_mss"),
        "data_as_of": MIDDAY_DATA_CUTOFF,
        "market_key_points": market_key_points,
        "macro_impact_line": macro_impact_line,
        "morning_reference": morning_reference,
    }

    risk_lines = build_holding_risk_lines(
        portfolio=portfolio,
        enriched=enriched,
        evaluation=scan_result.get("evaluation"),
        settings=settings,
    )

    audit_banner = ""
    if audit is not None and (not getattr(audit, "passed", True) or getattr(audit, "warnings", None)):
        parts = ["**⚠️ 数据审计提示**"]
        if not getattr(audit, "passed", True):
            parts.append("；".join(getattr(audit, "issues", []) or []))
        for w in getattr(audit, "warnings", []) or []:
            parts.append(f"- {w}")
        audit_banner = "\n".join(parts)

    return MiddayCardContext(
        plan_rows=plan_rows,
        plan_unchanged=plan_unchanged,
        session_brief=session_brief,
        risk_lines=risk_lines[:5],
        audit_banner=audit_banner,
        data_as_of=MIDDAY_DATA_CUTOFF,
        data_quality_notes=data_quality_notes,
        morning_diverged=morning_diverged,
        morning_diverged_note=morning_diverged_note,
        market_key_points=market_key_points,
        macro_impact_line=macro_impact_line,
        morning_reference=morning_reference,
        settings=settings,
    )


def render_plan_verify_markdown(ctx: MiddayCardContext) -> str:
    from agent_reach.daily_run.midday_content_scope import compact_afternoon_display

    lines: list[str] = []
    if ctx.audit_banner:
        lines.extend([ctx.audit_banner, "", "---", ""])

    lines.append(f"**{ctx.data_as_of or MIDDAY_DATA_CUTOFF}**")
    for note in ctx.data_quality_notes or []:
        lines.append(f"- {note}")

    if ctx.morning_diverged_note:
        lines.extend(["", ctx.morning_diverged_note])

    if not ctx.plan_rows:
        lines.extend(["", "- 无早盘操作清单，下午维持持仓观察"])
        return "\n".join(lines).strip()

    lines.extend(
        [
            "",
            "**早盘验证**",
            "",
            "| 股票 | 早盘计划 | 上午实际 | 验证结果 |",
            "|------|----------|----------|----------|",
        ]
    )
    for row in ctx.plan_rows:
        verify = str(row.get("verify") or "—")
        source = str(row.get("verify_source") or "").strip()
        if source and source not in verify:
            verify = f"{verify}（{source}）"
        lines.append(
            f"| {row.get('name')} | {row.get('morning_plan')} | {row.get('am_actual')} | {verify} |"
        )

    lines.extend(
        [
            "",
            "**下午展望**",
            "",
            "| 股票 | 下午操作 |",
            "|------|----------|",
        ]
    )
    for row in ctx.plan_rows:
        afternoon = compact_afternoon_display(row)
        if row.get("changed") and afternoon != "维持早盘计划" and "**" not in afternoon:
            afternoon = f"**{afternoon}**"
        lines.append(f"| {row.get('name')} | {afternoon} |")
    return "\n".join(lines).strip()


def render_session_brief_markdown(ctx: MiddayCardContext) -> str:
    brief = ctx.session_brief or {}
    if not brief and not ctx.market_key_points:
        return ""

    lines = [f"**{ctx.data_as_of or MIDDAY_DATA_CUTOFF}**"]
    key_points = list(ctx.market_key_points or brief.get("market_key_points") or [])
    if key_points:
        lines.append(f"- {'，'.join(key_points[:5])}")

    macro_line = str(ctx.macro_impact_line or brief.get("macro_impact_line") or "").strip()
    if macro_line:
        lines.append(f"- {macro_line}")

    morning_ref = str(ctx.morning_reference or brief.get("morning_reference") or "").strip()
    if morning_ref:
        lines.append(f"- {morning_ref}")

    if not key_points and not macro_line:
        mss = brief.get("mss")
        if mss is not None:
            lines.append(f"- 组合 MSS **{float(mss):.0f}** · **{brief.get('verdict', '观察')}**")
    return "\n".join(lines).strip()


def render_afternoon_risk_markdown(ctx: MiddayCardContext) -> str:
    if not ctx.risk_lines:
        return "- 暂无个股特有风险"
    return "\n".join(ctx.risk_lines[:5]).strip()


_CARD_RENDERERS = {
    "plan_verify": render_plan_verify_markdown,
    "session_brief": render_session_brief_markdown,
    "afternoon_risk": render_afternoon_risk_markdown,
}


def render_midday_card_sections(ctx: MiddayCardContext) -> list[ReportSection]:
    sections: list[ReportSection] = []
    for category in MIDDAY_CARD_ORDER:
        renderer = _CARD_RENDERERS[category]
        body = renderer(ctx)
        if not (body or "").strip():
            continue
        sections.append(ReportSection(category=category, title="", body=body.strip()))
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        label = MIDDAY_CARD_LABELS.get(sec.category, sec.category)
        sec.title = f"{label} {i}/{total}"
    return sections


def render_midday_cards_markdown(ctx: MiddayCardContext) -> str:
    parts = [sec.body for sec in render_midday_card_sections(ctx) if sec.body.strip()]
    return "\n\n---\n\n".join(parts).strip()
