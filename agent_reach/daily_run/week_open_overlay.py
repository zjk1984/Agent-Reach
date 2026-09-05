# -*- coding: utf-8
"""Sunday forecast operation_plans → weekday morning-session intraday overlay."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.pm_session_overlay import _patch_threshold, _patch_trade_every_n
from agent_reach.daily_run.trade_calendar import today_shanghai

_HANDOFF_DIR = Path.home() / ".agent-reach" / "daily_run" / "handoff"


def week_open_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("week_open") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "morning_session_only": raw.get("morning_session_only", True) is not False,
        "defensive_plan_keywords": tuple(
            str(x) for x in (raw.get("defensive_plan_keywords") or ("减仓", "卖出", "止损", "清仓"))
        ),
        "supportive_plan_keywords": tuple(
            str(x) for x in (raw.get("supportive_plan_keywords") or ("买入", "新建仓", "加仓"))
        ),
        "defensive_plan_count": int(raw.get("defensive_plan_count", 2)),
        "supportive_plan_count": int(raw.get("supportive_plan_count", 2)),
        "low_confidence_pct": float(raw.get("low_confidence_pct", 50.0)),
        "aggressive_entry_delta": float(raw.get("aggressive_entry_delta", 1.5)),
        "macro_veto_delta": float(raw.get("macro_veto_delta", 1.5)),
        "trade_every_n_delta": int(raw.get("trade_every_n_delta", 1)),
        "supportive_aggressive_entry_delta": float(raw.get("supportive_aggressive_entry_delta", -1.0)),
        "supportive_trade_every_n_delta": int(raw.get("supportive_trade_every_n_delta", -1)),
    }


def week_open_overlay_path(week_start: date) -> Path:
    return _HANDOFF_DIR / f"week_open_{week_start.isoformat()}.json"


def last_week_open_overlay_path() -> Path:
    return _HANDOFF_DIR / "last_week_open_overlay.json"


def week_open_overlay_active(settings: dict[str, Any]) -> bool:
    runtime = settings.get("harness_runtime") or {}
    return bool((runtime.get("week_open") or {}).get("active"))


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_overlay(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_overlay(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def classify_week_open_regime(
    *,
    operation_plans: list[dict[str, Any]],
    outlook: Optional[dict[str, Any]] = None,
    cfg: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    defensive = 0
    supportive = 0
    low_conf = 0

    for plan in operation_plans or []:
        text = str(plan.get("operation_plan") or plan.get("action") or "")
        conf = _optional_float(plan.get("confidence_pct"))
        if conf is not None and conf < cfg["low_confidence_pct"]:
            low_conf += 1
        if any(k in text for k in cfg["defensive_plan_keywords"]):
            defensive += 1
        if any(k in text for k in cfg["supportive_plan_keywords"]):
            supportive += 1

    outlook = outlook or {}
    for row in outlook.get("risk_calendar") or []:
        if str(row.get("severity") or "").lower() in {"high", "高"}:
            defensive += 1
            reasons.append(f"风险日历：{str(row.get('event') or '')[:40]}")

    if low_conf >= cfg["defensive_plan_count"]:
        reasons.append(f"{low_conf} 条操作计划置信度低于 {cfg['low_confidence_pct']:.0f}%")
    if defensive >= cfg["defensive_plan_count"]:
        reasons.append(f"{defensive} 条偏防御操作计划")
        return "defensive", reasons
    if supportive >= cfg["supportive_plan_count"] and defensive == 0:
        reasons.append(f"{supportive} 条偏进攻操作计划")
        return "supportive", reasons
    return "neutral", reasons or ["周日预测操作计划中"]


def build_week_open_overlay_payload(
    *,
    forecast: dict[str, Any],
    outlook: Optional[dict[str, Any]] = None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    cfg = week_open_cfg(settings)
    plans = list(forecast.get("operation_plans") or [])
    regime, reasons = classify_week_open_regime(
        operation_plans=plans,
        outlook=outlook or forecast.get("outlook"),
        cfg=cfg,
    )
    from agent_reach.daily_run.session_overlay import build_symbol_gates

    return {
        "week_start": str(forecast.get("week_start") or ""),
        "week_end": str(forecast.get("week_end") or ""),
        "regime": regime,
        "reasons": reasons,
        "plan_count": len(plans),
        "operation_plans": plans[:8],
        "symbol_gates": build_symbol_gates(plans, cfg=cfg),
        "enabled": cfg["enabled"],
    }


def save_week_open_overlay(payload: dict[str, Any]) -> Path:
    week_start_s = str(payload.get("week_start") or "")
    try:
        week_start = date.fromisoformat(week_start_s)
    except ValueError:
        from agent_reach.daily_run.week_forecast import next_trading_week_range

        week_start, _ = next_trading_week_range()
        payload = {**payload, "week_start": week_start.isoformat()}
    path = week_open_overlay_path(week_start)
    _write_overlay(path, payload)
    _write_overlay(last_week_open_overlay_path(), payload)
    try:
        from agent_reach.daily_run.storage.hooks import on_week_open_overlay

        on_week_open_overlay(payload, source_path=str(path))
    except Exception:
        pass
    return path


def load_week_open_overlay(*, as_of: Optional[date] = None) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.week_forecast import load_active_forecast

    d = as_of or today_shanghai()
    active = load_active_forecast(d)
    if active:
        ws = str(active.get("week_start") or "")
        if ws:
            hit = _read_overlay(week_open_overlay_path(date.fromisoformat(ws)))
            if hit:
                return hit
    hit = _read_overlay(last_week_open_overlay_path())
    return hit


def build_and_save_week_open_overlay(
    forecast: dict[str, Any],
    *,
    outlook: Optional[dict[str, Any]] = None,
    settings: dict[str, Any],
) -> Optional[Path]:
    cfg = week_open_cfg(settings)
    if not cfg["enabled"]:
        return None
    payload = build_week_open_overlay_payload(
        forecast=forecast,
        outlook=outlook,
        settings=settings,
    )
    return save_week_open_overlay(payload)


def apply_week_open_overlay(
    settings: dict[str, Any],
    scans: list[dict[str, Any]],
    *,
    dt=None,
) -> dict[str, Any]:
    """Backward-compatible alias; prefer session_overlay.apply_session_overlay."""
    from agent_reach.daily_run.session_overlay import apply_session_overlay

    return apply_session_overlay(settings, scans, dt=dt)
