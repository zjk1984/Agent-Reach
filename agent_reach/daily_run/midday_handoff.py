# -*- coding: utf-8
"""Midday card handoff — morning plan verify, PM adjustments, close backtrack loop."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.snapshot_builder import _normalize_code

_HANDOFF_DIR = Path.home() / ".agent-reach" / "daily_run" / "handoff"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def midday_handoff_path(day: date) -> Path:
    return _HANDOFF_DIR / f"midday_{day.isoformat()}.json"


def last_midday_handoff_path() -> Path:
    return _HANDOFF_DIR / "last_midday_handoff.json"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_handoff(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_handoff(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _is_after_noon_shanghai(at_iso: str) -> bool:
    raw = str(at_iso or "").strip()
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(_SHANGHAI)
        return local.hour >= 12
    except ValueError:
        return False


def _collect_pm_trades_by_code(
    *,
    state: dict[str, Any],
    day: date,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, list[dict[str, Any]]]:
    from collections import defaultdict

    from agent_reach.daily_run.midday_cards import _fills_from_trade_record

    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in state.get("trades") or []:
        if not isinstance(trade, dict) or trade.get("portfolio_applied") is False:
            continue
        at = str(trade.get("as_of") or "")
        if not _is_after_noon_shanghai(at):
            continue
        for fill in _fills_from_trade_record(trade):
            code = _normalize_code(str(fill.get("code") or ""))
            if code:
                by_code[code].append(fill)

    try:
        from agent_reach.daily_run.realized_pnl import load_ledger_entries

        for entry in load_ledger_entries(start=day, end=day, settings=settings):
            if entry.get("portfolio_applied") is False:
                continue
            at = str(entry.get("at") or "")
            if not _is_after_noon_shanghai(at):
                continue
            for action in entry.get("actions") or []:
                if action.get("side") not in ("buy", "sell"):
                    continue
                code = _normalize_code(str(action.get("code") or ""))
                if code:
                    by_code[code].append(
                        {
                            "side": action.get("side"),
                            "code": code,
                            "price": action.get("price"),
                            "shares": action.get("shares"),
                            "at": at,
                        }
                    )
    except Exception:
        pass
    return dict(by_code)


def build_midday_handoff(
    ctx: Any,
    *,
    morning_handoff: Optional[dict[str, Any]] = None,
    portfolio: Optional[dict[str, Any]] = None,
    enriched: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Serialize midday card outputs for close-card backtrack."""
    from agent_reach.daily_run.midday_cards import MIDDAY_DATA_CUTOFF
    from agent_reach.daily_run.trade_calendar import today_shanghai

    day = today_shanghai()
    pf = portfolio or {}
    plan_rows = list(getattr(ctx, "plan_rows", None) or [])
    morning = morning_handoff or {}

    positions_at_morning = dict(morning.get("positions_at_morning") or {})
    if not positions_at_morning:
        for row in morning.get("action_checklist") or []:
            if not isinstance(row, dict):
                continue
            code = _normalize_code(str(row.get("code") or ""))
            if not code:
                continue
            positions_at_morning[code] = {
                "name": str(row.get("name") or code),
                "weight_pct": _optional_float(row.get("current_weight_pct")),
            }

    positions_at_am_close: dict[str, dict[str, Any]] = {}
    position_changes: list[dict[str, Any]] = []
    for brief in getattr(ctx, "holdings_am_rows", None) or []:
        code = _normalize_code(str(brief.get("code") or ""))
        if not code:
            continue
        positions_at_am_close[code] = {
            "name": brief.get("name"),
            "price": brief.get("am_close"),
            "change_pct": brief.get("change_pct"),
            "weight_pct": None,
        }
    for row in plan_rows:
        code = _normalize_code(str(row.get("code") or ""))
        if not code:
            continue
        am_w = _optional_float(row.get("am_weight_pct"))
        m_w = _optional_float(row.get("morning_weight_pct"))
        if code in positions_at_am_close and am_w is not None:
            positions_at_am_close[code]["weight_pct"] = am_w
        if m_w is not None or am_w is not None:
            position_changes.append(
                {
                    "code": code,
                    "name": row.get("name"),
                    "morning_weight_pct": m_w,
                    "am_close_weight_pct": am_w,
                }
            )

    morning_plan_verify = [
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "operation": r.get("verify_operation"),
            "trigger": r.get("trigger_cond"),
            "am_actual": r.get("verify_am_actual"),
            "status": r.get("verify_status"),
            "filled": bool(r.get("filled")),
        }
        for r in plan_rows
    ]
    afternoon_adjustments = [
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "original_plan": r.get("original_plan"),
            "adjusted_plan": r.get("adjusted_plan"),
            "adjust_reason": r.get("adjust_reason"),
            "afternoon_trigger": r.get("afternoon_trigger"),
            "changed": bool(r.get("changed")),
            "am_filled": bool(r.get("filled")),
            "morning_weight_pct": r.get("morning_weight_pct"),
            "am_weight_pct": r.get("am_weight_pct"),
        }
        for r in plan_rows
    ]

    structured_predictions = list(getattr(ctx, "prediction_verify_items", None) or [])
    if not structured_predictions:
        for line in getattr(ctx, "prediction_verify_lines", None) or []:
            structured_predictions.append({"markdown": str(line)})

    structured_anomalies = list(getattr(ctx, "anomaly_signal_items", None) or [])
    if not structured_anomalies:
        for line in getattr(ctx, "anomaly_signals", None) or []:
            text = str(line).lstrip("- ").strip()
            severity = "red" if "🔴" in text else "yellow"
            structured_anomalies.append({"severity": severity, "markdown": text})

    return {
        "midday_date": day.isoformat(),
        "source_morning_date": morning.get("morning_date") or day.isoformat(),
        "data_as_of": getattr(ctx, "data_as_of", None) or MIDDAY_DATA_CUTOFF,
        "morning_plan_verify": morning_plan_verify,
        "afternoon_adjustments": afternoon_adjustments,
        "holdings_am_brief": list(getattr(ctx, "holdings_am_rows", None) or []),
        "morning_prediction_verify": structured_predictions,
        "am_anomaly_signals": structured_anomalies,
        "timeline_nodes": list(getattr(ctx, "timeline_nodes", None) or []),
        "positions_at_morning": positions_at_morning,
        "positions_at_am_close": positions_at_am_close,
        "position_changes": position_changes,
        "morning_predictions": list(morning.get("morning_predictions") or []),
    }


def save_midday_handoff(payload: dict[str, Any]) -> Path:
    day_s = str(payload.get("midday_date") or "")
    try:
        day = date.fromisoformat(day_s)
    except ValueError:
        from agent_reach.daily_run.trade_calendar import today_shanghai

        day = today_shanghai()
        payload = {**payload, "midday_date": day.isoformat()}
    path = midday_handoff_path(day)
    _write_handoff(path, payload)
    _write_handoff(last_midday_handoff_path(), payload)
    return path


def load_midday_handoff(*, midday_day: Optional[date] = None) -> Optional[dict[str, Any]]:
    if midday_day is not None:
        hit = _read_handoff(midday_handoff_path(midday_day))
        if hit:
            return hit
    from agent_reach.daily_run.trade_calendar import today_shanghai

    hit = _read_handoff(midday_handoff_path(today_shanghai()))
    if hit:
        return hit
    return _read_handoff(last_midday_handoff_path())


def validate_midday_adjustments(
    ctx: Any,
    handoff: Optional[dict[str, Any]] = None,
    *,
    state: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Close card: verify PM execution vs midday afternoon adjustments."""
    from agent_reach.daily_run.close_morning_handoff import collect_close_positions
    from agent_reach.daily_run.trade_calendar import today_shanghai

    payload = handoff or load_midday_handoff(midday_day=today_shanghai())
    if not payload:
        return []

    close_positions = collect_close_positions(ctx)
    pm_trades = _collect_pm_trades_by_code(state=state or {}, day=today_shanghai(), settings=settings)
    lines: list[str] = []

    for adj in payload.get("afternoon_adjustments") or []:
        if not isinstance(adj, dict):
            continue
        code = _normalize_code(str(adj.get("code") or ""))
        name = str(adj.get("name") or code or "—")
        original = str(adj.get("original_plan") or "—")
        adjusted = str(adj.get("adjusted_plan") or "—")
        am_weight = _optional_float(adj.get("am_weight_pct"))
        close_weight = _optional_float((close_positions.get(code) or {}).get("weight_pct"))
        pm_fills = pm_trades.get(code) or []
        pm_sells = [f for f in pm_fills if f.get("side") == "sell"]
        pm_buys = [f for f in pm_fills if f.get("side") == "buy"]

        if adj.get("am_filled") and adjusted in {"维持", original}:
            mark = "✅"
            detail = f"上午已执行，收盘 **{close_weight:.1f}%**" if close_weight is not None else "上午已执行"
        elif adjusted == "维持" and not adj.get("changed"):
            if close_weight is not None and am_weight is not None and abs(close_weight - am_weight) <= 1.0:
                mark = "✅"
                detail = f"收盘仓位 **{close_weight:.1f}%**，与午盘一致"
            elif not pm_fills:
                mark = "✅"
                detail = "下午无额外调仓"
            else:
                mark = "⚠️"
                detail = f"下午有成交但仓位 **{close_weight:.1f}%**" if close_weight is not None else "下午有成交"
        elif adjusted == "减仓":
            if pm_sells or (
                close_weight is not None and am_weight is not None and close_weight < am_weight - 0.4
            ):
                mark = "✅"
                detail = f"下午已减仓，收盘 **{close_weight:.1f}%**" if close_weight is not None else "下午有卖出"
            else:
                mark = "❌"
                detail = "午盘计划减仓，下午未执行"
        elif adjusted == "观望":
            if not pm_buys and (close_weight is None or am_weight is None or close_weight <= am_weight + 0.5):
                mark = "✅"
                detail = "下午按观望执行"
            else:
                mark = "⚠️"
                detail = "下午仍有买入或仓位上升"
        elif adjusted == "加仓":
            if pm_buys or (
                close_weight is not None and am_weight is not None and close_weight > am_weight + 0.4
            ):
                mark = "✅"
                detail = f"下午已加仓，收盘 **{close_weight:.1f}%**" if close_weight is not None else "下午有买入"
            else:
                mark = "❌"
                detail = "午盘计划加仓，下午未执行"
        else:
            mark = "—"
            detail = "待确认"

        lines.append(
            f"- **{name}** 午盘 {original}→{adjusted} → {mark} {detail}"
        )
    return lines[:8]


def validate_midday_anomaly_signals(
    ctx: Any,
    handoff: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Close card: check whether AM anomalies fermented in the afternoon."""
    payload = handoff or load_midday_handoff()
    if not payload:
        return []

    close_by_code: dict[str, dict[str, Any]] = {}
    for row in getattr(ctx, "symbol_rows", None) or []:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        if code:
            close_by_code[code] = row

    lines: list[str] = []
    for sig in payload.get("am_anomaly_signals") or []:
        if not isinstance(sig, dict):
            continue
        text = str(sig.get("text") or sig.get("markdown") or "").strip()
        code = _normalize_code(str(sig.get("code") or ""))
        name = str(sig.get("name") or code or "市场")
        am_pct = _optional_float(sig.get("change_pct"))
        severity = str(sig.get("severity") or "yellow")

        close_row = close_by_code.get(code) or {}
        close_pct = _optional_float(close_row.get("change_pct"))
        if close_pct is None:
            verify = (getattr(ctx, "verify_by_code", None) or {}).get(code) or {}
            close_pct = _optional_float(verify.get("price_delta_pct"))

        if am_pct is not None and close_pct is not None:
            if severity == "red" and close_pct <= am_pct - 1.0:
                lines.append(
                    f"- 🔴 **{name}** 上午异常下午发酵：上午 {am_pct:+.2f}% → 收盘 {close_pct:+.2f}%"
                )
            elif close_pct >= am_pct + 1.5:
                lines.append(
                    f"- ✅ **{name}** 上午异常已缓解：上午 {am_pct:+.2f}% → 收盘 {close_pct:+.2f}%"
                )
            else:
                lines.append(
                    f"- 🟡 **{name}** 下午震荡，持续观察：上午 {am_pct:+.2f}% → 收盘 {close_pct:+.2f}%"
                )
        elif text:
            icon = "🔴" if severity == "red" else "🟡"
            clean = re.sub(r"^[-🔴🟡\s]+", "", text)
            lines.append(f"- {icon} {clean[:100]} → 收盘继续跟踪")

    return lines[:6]


def render_midday_close_loop_markdown(
    ctx: Any,
    *,
    state: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    handoff = load_midday_handoff()
    if not handoff:
        return ""

    if state is None:
        try:
            from agent_reach.daily_run.intraday import load_state

            state = load_state().to_dict()
        except Exception:
            state = {}

    adj = validate_midday_adjustments(ctx, handoff, state=state, settings=settings or getattr(ctx, "settings", None))
    anomalies = validate_midday_anomaly_signals(ctx, handoff)
    if not adj and not anomalies:
        return ""

    parts: list[str] = ["**午盘→收盘回溯**", ""]
    if adj:
        parts.extend(["**下午操作验证（相对午盘调整）**", ""])
        parts.extend(adj)
    if anomalies:
        parts.extend(["", "**上午异常信号跟踪**", ""])
        parts.extend(anomalies)
    return "\n".join(parts).strip()
