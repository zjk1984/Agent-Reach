# -*- coding: utf-8
"""Close ↔ morning card handoff — prediction verify, positions, risks, action trace."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_HANDOFF_DIR = Path.home() / ".agent-reach" / "daily_run" / "handoff"


def handoff_dir() -> Path:
    return _HANDOFF_DIR


def close_handoff_path(day: date) -> Path:
    return _HANDOFF_DIR / f"close_{day.isoformat()}.json"


def morning_handoff_path(day: date) -> Path:
    return _HANDOFF_DIR / f"morning_{day.isoformat()}.json"


def last_close_handoff_path() -> Path:
    return _HANDOFF_DIR / "last_close_handoff.json"


def last_morning_handoff_path() -> Path:
    return _HANDOFF_DIR / "last_morning_handoff.json"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_handoff(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_handoff(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def collect_tomorrow_focus_items(ctx: Any) -> list[dict[str, Any]]:
    """Structured items from close card「明日关注」."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        text: str,
        *,
        code: str = "",
        name: str = "",
        kind: str = "focus",
    ) -> None:
        line = str(text or "").strip()
        if not line or line in seen:
            return
        seen.add(line)
        items.append(
            {
                "kind": kind,
                "code": _normalize_code(code) if code else "",
                "name": str(name or "").strip(),
                "text": line[:160],
            }
        )

    for row in ctx.symbol_rows:
        code = str(row.get("code") or "")
        name = str(row.get("name") or code)
        verify = row.get("verify") or ctx.verify_by_code.get(code) or {}
        for rec in verify.get("recommendations") or []:
            _add(str(rec), code=code, name=name, kind="recommendation")

    for sc in (ctx.technical_scenarios or [])[:5]:
        code = str(sc.get("code") or "")
        name = str(sc.get("name") or code or "—")
        bull = (sc.get("bullish") or {}).get("label")
        bear = (sc.get("bearish") or {}).get("label")
        if bull:
            _add(f"触发做多：{bull}", code=code, name=name, kind="bullish")
        if bear:
            _add(f"触发减仓：{bear}", code=code, name=name, kind="bearish")

    narrative = ctx.narrative or {}
    if not narrative.get("skipped"):
        for point in narrative.get("focus_points") or []:
            _add(str(point), kind="narrative")

    for item in (ctx.improvements or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get("detail") or item.get("title") or "").strip()
        if not detail:
            continue
        if "明日" in detail or "早盘" in detail or item.get("priority") == "high":
            _add(detail, kind="improvement")

    deploy = ctx.portfolio_summary.get("deploy_budget_line")
    if deploy:
        _add(str(deploy), kind="deploy")

    return items[:8]


def collect_watch_risk_items(ctx: Any) -> list[dict[str, Any]]:
    """Structured「待观察风险」from close key signals / narrative."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        text: str,
        *,
        code: str = "",
        name: str = "",
        kind: str = "watch",
    ) -> None:
        line = str(text or "").strip()
        if not line or line in seen:
            return
        seen.add(line)
        items.append(
            {
                "kind": kind,
                "code": _normalize_code(code) if code else "",
                "name": str(name or "").strip(),
                "text": line[:160],
                "status": "watch",
            }
        )

    for sc in (ctx.technical_scenarios or [])[:6]:
        code = str(sc.get("code") or "")
        name = str(sc.get("name") or code or "—")
        scenario_type = str(sc.get("scenario_type") or "")
        if scenario_type == "upper_shadow":
            _add(
                f"长上影，关注支撑 {sc.get('session_low')}",
                code=code,
                name=name,
                kind="technical",
            )
        elif scenario_type == "liquidity_shrink":
            _add("缩量回调，警惕流动性萎缩", code=code, name=name, kind="technical")
        bear = (sc.get("bearish") or {}).get("label")
        if bear:
            _add(str(bear), code=code, name=name, kind="bearish")

    narrative = ctx.narrative or {}
    for alert in narrative.get("risk_alerts") or []:
        _add(str(alert), kind="narrative_risk")

    pf = ctx.portfolio_summary or {}
    for line in pf.get("reason_lines") or []:
        text = str(line).strip()
        if "⚠" in text or "风险" in text or "回避" in text:
            _add(text, kind="portfolio")

    return items[:8]


def collect_close_positions(ctx: Any) -> dict[str, dict[str, Any]]:
    """Final close weights keyed by normalized code."""
    pf = ctx.portfolio_summary or {}
    holdings = list(pf.get("holdings") or [])
    end_total = _optional_float(pf.get("end_total") or pf.get("total"))
    positions: dict[str, dict[str, Any]] = {}

    for row in holdings:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        if not code:
            continue
        weight = _optional_float(row.get("weight_pct"))
        shares = int(row.get("shares") or 0)
        price = _optional_float(row.get("price"))
        if weight is None and end_total and shares > 0 and price is not None:
            weight = round(shares * price / end_total * 100.0, 1)
        positions[code] = {
            "name": str(row.get("name") or code),
            "weight_pct": weight,
            "shares": shares,
            "close_price": price,
        }
    return positions


def build_close_handoff(ctx: Any) -> dict[str, Any]:
    from agent_reach.daily_run.quant_calibration import build_next_day_session_seed
    from agent_reach.daily_run.trade_calendar import today_shanghai

    day = today_shanghai()
    settings = getattr(ctx, "settings", None)
    payload: dict[str, Any] = {
        "close_date": day.isoformat(),
        "tomorrow_focus": collect_tomorrow_focus_items(ctx),
        "watch_risks": collect_watch_risk_items(ctx),
        "positions": collect_close_positions(ctx),
        "portfolio_total": _optional_float((ctx.portfolio_summary or {}).get("end_total")),
        "next_day_session_seed": build_next_day_session_seed(
            portfolio_summary=ctx.portfolio_summary,
            settings=settings,
        ),
    }
    if day.weekday() == 4:
        pf = ctx.portfolio_summary or {}
        try:
            from agent_reach.daily_run.weekly_signals import build_next_week_outlook

            outlook = build_next_week_outlook(
                week_end=day,
                holdings=list(pf.get("holdings") or []),
                watchlist=list(pf.get("watchlist") or []),
                settings=settings,
            )
            payload["next_week_outlook"] = {
                "operation_plan": outlook.get("operation_plan") or [],
                "risk_calendar": outlook.get("risk_calendar") or [],
                "next_week_start": outlook.get("next_week_start"),
                "next_week_end": outlook.get("next_week_end"),
            }
        except Exception:
            pass
    return payload


def save_close_handoff(payload: dict[str, Any]) -> Path:
    day_s = str(payload.get("close_date") or "")
    try:
        day = date.fromisoformat(day_s)
    except ValueError:
        from agent_reach.daily_run.trade_calendar import today_shanghai

        day = today_shanghai()
        payload = {**payload, "close_date": day.isoformat()}
    path = close_handoff_path(day)
    _write_handoff(path, payload)
    _write_handoff(last_close_handoff_path(), payload)
    try:
        from agent_reach.daily_run.storage.hooks import on_close_handoff

        on_close_handoff(payload, source_path=str(path))
    except Exception:
        pass
    return path


def load_close_handoff(
    *,
    close_day: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if close_day is not None:
        hit = _read_handoff(close_handoff_path(close_day))
        if hit:
            return hit
    from agent_reach.daily_run.prior_close import prev_trading_day
    from agent_reach.daily_run.trade_calendar import today_shanghai

    yday = prev_trading_day(today_shanghai(), settings=settings or {})
    hit = _read_handoff(close_handoff_path(yday))
    if hit:
        return hit
    return _read_handoff(last_close_handoff_path())


def load_close_handoff_for_morning(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    return load_close_handoff(settings=settings)


def collect_morning_predictions(ctx: Any, action_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structured morning predictions for midday verify loop."""
    from agent_reach.daily_run.morning_signals import _prediction_text_from_baseline

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    sym_by_code = {_normalize_code(sym.code): sym for sym in ctx.symbol_rows}

    for sym in ctx.symbol_rows:
        code = _normalize_code(sym.code)
        if not code or code in seen:
            continue
        report = sym.report or {}
        prediction = _prediction_text_from_baseline(report)
        if not prediction or prediction == "震荡观察":
            continue
        items.append(
            {
                "code": code,
                "name": sym.name,
                "prediction": prediction[:48],
                "source": "report",
            }
        )
        seen.add(code)

    for row in action_rows:
        name = str(row.get("name") or "").strip()
        sym = sym_by_code.get(_normalize_code(str(row.get("code") or "")))
        if sym is None:
            for candidate in ctx.symbol_rows:
                if candidate.name == name:
                    sym = candidate
                    break
        code = _normalize_code(getattr(sym, "code", "") if sym else str(row.get("code") or ""))
        note = str(row.get("reasoning") or row.get("note") or row.get("target_position") or "").strip()
        if not code or not note or code in seen:
            continue
        items.append(
            {
                "code": code,
                "name": name or (sym.name if sym else code),
                "prediction": note[:48],
                "source": "action_checklist",
            }
        )
        seen.add(code)
    return items[:6]


def build_morning_handoff(
    ctx: Any,
    action_rows: list[dict[str, Any]],
    *,
    am_open_overlay: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.trade_calendar import today_shanghai

    close_handoff = getattr(ctx, "close_handoff", None) or {}
    checklist: list[dict[str, Any]] = []
    sym_by_name = {row.name: row for row in ctx.symbol_rows}
    for row in action_rows:
        sym = sym_by_name.get(row.get("name") or "")
        code = _normalize_code(getattr(sym, "code", "") if sym else "")
        current = _optional_float(row.get("current_weight_pct"))
        target = _optional_float(row.get("target_weight_pct"))
        checklist.append({**row, "code": code, "current_weight_pct": current, "target_weight_pct": target})

    payload = {
        "morning_date": today_shanghai().isoformat(),
        "source_close_date": close_handoff.get("close_date"),
        "action_checklist": checklist,
        "positions_at_morning": dict(close_handoff.get("positions") or {}),
        "morning_predictions": collect_morning_predictions(ctx, action_rows),
    }
    if am_open_overlay:
        payload["am_open_overlay"] = dict(am_open_overlay)
    return payload


def save_morning_handoff(payload: dict[str, Any]) -> Path:
    day_s = str(payload.get("morning_date") or "")
    try:
        day = date.fromisoformat(day_s)
    except ValueError:
        from agent_reach.daily_run.trade_calendar import today_shanghai

        day = today_shanghai()
        payload = {**payload, "morning_date": day.isoformat()}
    path = morning_handoff_path(day)
    _write_handoff(path, payload)
    _write_handoff(last_morning_handoff_path(), payload)
    return path


def load_morning_handoff(*, morning_day: Optional[date] = None) -> Optional[dict[str, Any]]:
    if morning_day is not None:
        hit = _read_handoff(morning_handoff_path(morning_day))
        if hit:
            return hit
    from agent_reach.daily_run.trade_calendar import today_shanghai

    hit = _read_handoff(morning_handoff_path(today_shanghai()))
    if hit:
        return hit
    return _read_handoff(last_morning_handoff_path())


def _symbol_row_map(ctx: Any) -> dict[str, Any]:
    by_code: dict[str, Any] = {}
    by_name: dict[str, Any] = {}
    for sym in ctx.symbol_rows:
        by_code[_normalize_code(sym.code)] = sym
        by_name[str(sym.name)] = sym
    return {"code": by_code, "name": by_name}


def _describe_actual_move(holding: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, Optional[float]]:
    from agent_reach.daily_run.morning_signals import _prev_close_value

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
        parts.append(
            f"{'高开' if open_gap > 0.15 else '低开' if open_gap < -0.15 else '平开'} {abs(open_gap):.1f}%"
        )
    parts.append(f"当前 {current_pct:+.1f}%")
    return "，".join(parts), current_pct


def _prediction_hit(text: str, holding: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    from agent_reach.daily_run.morning_signals import _prediction_hit as _hit

    return _hit(text, holding, snapshot)


def validate_tomorrow_focus_lines(ctx: Any, *, limit: int = 2) -> list[str]:
    handoff = getattr(ctx, "close_handoff", None) or load_close_handoff_for_morning(
        settings=getattr(ctx, "settings", None)
    )
    if not handoff:
        return []
    maps = _symbol_row_map(ctx)
    lines: list[str] = []
    for item in handoff.get("tomorrow_focus") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        code = str(item.get("code") or "")
        name = str(item.get("name") or "")
        sym = maps["code"].get(_normalize_code(code)) if code else None
        if sym is None and name:
            sym = maps["name"].get(name)
        if sym is None and ctx.symbol_rows:
            sym = ctx.symbol_rows[0]
        holding = (sym.holding if sym else {}) or {}
        snapshot = (sym.snapshot if sym else {}) or {}
        label = name or (sym.name if sym else "组合")
        actual, _pct = _describe_actual_move(holding, snapshot)
        hit = _prediction_hit(text, holding, snapshot)
        mark = "✅" if hit else "❌"
        lines.append(f"- 昨日关注「{label} {text}」→ {mark} 实际{actual}")
        if len(lines) >= limit:
            break
    return lines


def render_yesterday_focus_validation_markdown(ctx: Any) -> str:
    lines = validate_tomorrow_focus_lines(ctx, limit=2)
    if not lines:
        return ""
    return "**昨日预测验证**\n\n" + "\n".join(lines)


def _parse_weight_from_label(label: str) -> tuple[Optional[float], Optional[float]]:
    text = str(label or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*→\s*(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"维持\s*(\d+(?:\.\d+)?)\s*%", text)
    if match:
        val = float(match.group(1))
        return val, val
    return None, None


def close_position_weight(
    ctx: Any,
    code: str,
    *,
    fallback_holding: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    handoff = getattr(ctx, "close_handoff", None) or {}
    pos = (handoff.get("positions") or {}).get(_normalize_code(code))
    if isinstance(pos, dict) and pos.get("weight_pct") is not None:
        return float(pos["weight_pct"])
    if fallback_holding is not None:
        from agent_reach.daily_run.morning_cards import _holding_weight_pct

        return _holding_weight_pct(fallback_holding, ctx.portfolio)
    return None


def render_risk_tracking_markdown(ctx: Any) -> list[str]:
    handoff = getattr(ctx, "close_handoff", None) or load_close_handoff_for_morning(
        settings=getattr(ctx, "settings", None)
    )
    if not handoff:
        return []
    maps = _symbol_row_map(ctx)
    lines: list[str] = []
    for item in handoff.get("watch_risks") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        code = str(item.get("code") or "")
        name = str(item.get("name") or "") or code or "组合"
        sym = maps["code"].get(_normalize_code(code)) if code else maps["name"].get(name)
        holding = (sym.holding if sym else {}) or {}
        snapshot = (sym.snapshot if sym else {}) or {}
        report = (sym.report if sym else {}) or {}
        status, detail = _assess_risk_status(text, holding, snapshot, report)
        lines.append(f"- **{name}** {text[:72]} → **{status}**（{detail}）")
    return lines[:6]


def _assess_risk_status(
    text: str,
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    report: dict[str, Any],
) -> tuple[str, str]:
    price = _optional_float(holding.get("price") or snapshot.get("open") or snapshot.get("price"))
    stop = _optional_float(report.get("stop_loss_price"))
    ma20 = _optional_float(holding.get("ma20") or snapshot.get("ma20"))
    _actual, pct = _describe_actual_move(holding, snapshot)

    if "支撑" in text or "跌破" in text:
        level_match = re.search(r"(\d+(?:\.\d+)?)", text)
        level = float(level_match.group(1)) if level_match else None
        if level is not None and price is not None and price <= level:
            return "已触发", f"现价 {price:.2f} ≤ {level:.2f}"
        return "仍待观察", _actual

    if "止损" in text or "减仓" in text:
        if stop is not None and price is not None and price <= stop:
            return "已触发", f"触及止损 {stop:.2f}"
        return "仍待观察", _actual

    if "缩量" in text or "流动性" in text:
        vol = _optional_float(holding.get("volume_ratio") or snapshot.get("volume_ratio"))
        if vol is not None and vol < 0.85:
            return "已触发", f"量比 {vol:.1f}x"
        return "仍待观察", f"量比 {vol:.1f}x" if vol is not None else _actual

    if ma20 is not None and price is not None and price < ma20:
        return "已触发", f"跌破 MA20 {ma20:.2f}"

    if pct is not None and pct <= -2.0 and ("回避" in text or "风险" in text):
        return "已触发", _actual
    if pct is not None and abs(pct) <= 1.0:
        return "已解除", _actual
    return "仍待观察", _actual


def validate_morning_action_lines(ctx: Any) -> list[str]:
    from agent_reach.daily_run.trade_calendar import today_shanghai

    handoff = load_morning_handoff(morning_day=today_shanghai())
    if not handoff:
        return []

    close_positions = collect_close_positions(ctx)
    lines: list[str] = []
    for action in handoff.get("action_checklist") or []:
        if not isinstance(action, dict):
            continue
        code = _normalize_code(str(action.get("code") or ""))
        name = str(action.get("name") or code or "—")
        operation = str(action.get("operation") or "")
        morning_current = _optional_float(action.get("current_weight_pct"))
        morning_target = _optional_float(action.get("target_weight_pct"))
        if morning_current is None or morning_target is None:
            cur, tgt = _parse_weight_from_label(str(action.get("target_position") or ""))
            morning_current = morning_current if morning_current is not None else cur
            morning_target = morning_target if morning_target is not None else tgt

        actual = _optional_float((close_positions.get(code) or {}).get("weight_pct"))
        if actual is None:
            lines.append(f"- **{name}** {operation} → ⚠️ 无收盘仓位数据")
            continue

        hit = _action_executed(
            operation=operation,
            morning_current=morning_current,
            morning_target=morning_target,
            actual_weight=actual,
        )
        mark = "✅" if hit else "❌"
        target_s = f"{morning_target:.0f}%" if morning_target is not None else "—"
        lines.append(
            f"- **{name}** 早盘建议 {operation}（目标 {target_s}）→ {mark} 收盘仓位 **{actual:.1f}%**"
        )
    return lines[:6]


def _action_executed(
    *,
    operation: str,
    morning_current: Optional[float],
    morning_target: Optional[float],
    actual_weight: float,
) -> bool:
    if morning_target is None and morning_current is None:
        return True
    target = morning_target if morning_target is not None else morning_current
    current = morning_current if morning_current is not None else actual_weight
    if target is None:
        return True
    if operation == "减仓":
        return actual_weight <= target + 0.6 or (current is not None and actual_weight < current - 0.4)
    if operation == "加仓":
        return actual_weight >= target - 0.6 or (current is not None and actual_weight > current + 0.4)
    if operation in ("观望", "持有"):
        anchor = current if current is not None else target
        return abs(actual_weight - anchor) <= 1.2
    return abs(actual_weight - target) <= 1.2


def render_morning_action_trace_markdown(ctx: Any) -> str:
    lines = validate_morning_action_lines(ctx)
    if not lines:
        return ""
    return "**早盘操作回溯**\n\n" + "\n".join(lines)


def format_tomorrow_focus_markdown(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            lines.append(f"- **{name}：** {text[:120]}")
        else:
            lines.append(f"- {text[:120]}")
    return "\n".join(lines[:8]).strip()
