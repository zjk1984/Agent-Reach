# -*- coding: utf-8 -*-
"""Technical scenario watch — upper-shadow reversal setups and follow-up eval."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import next_trading_day, today_shanghai


def technical_watch_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("technical_watch") or {})
    return {
        "enabled": block.get("enabled", True),
        "min_upper_shadow_ratio": float(block.get("min_upper_shadow_ratio", 0.35)),
        "min_spike_pct": float(block.get("min_spike_pct", 3.0)),
        "eval_days": int(block.get("eval_days", 5)),
        "reclaim_high_tolerance_pct": float(block.get("reclaim_high_tolerance_pct", 1.5)),
        "gap_up_pct": float(block.get("gap_up_pct", 1.0)),
    }


def default_scenarios_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "technical_scenarios.json"


def load_scenarios(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or default_scenarios_path()
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = raw if isinstance(raw, list) else list(raw.get("scenarios") or [])
    return [dict(row) for row in rows if isinstance(row, dict)]


def save_scenarios(scenarios: list[dict[str, Any]], path: Optional[Path] = None) -> Path:
    p = path or default_scenarios_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": "1.0", "scenarios": scenarios}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _scenario_key(code: str, setup_date: str) -> str:
    return f"{_normalize_code(code)}/{setup_date}"


def register_upper_shadow_scenario(
    *,
    code: str,
    name: str,
    setup_date: str,
    session_high: float,
    session_close: float,
    session_low: float,
    settings: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
    note: str = "",
) -> dict[str, Any]:
    """Persist an upper-shadow follow-up scenario for the next trading session(s)."""
    cfg = technical_watch_cfg(settings)
    norm = _normalize_code(code)
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from_d = next_trading_day(setup, settings=settings)
    eval_from = eval_from_d.isoformat()
    eval_until = (eval_from_d + timedelta(days=max(1, cfg["eval_days"]))).isoformat()
    shadow = float(session_high) - max(float(session_close), float(session_low))
    span = max(float(session_high) - float(session_low), 0.01)
    scenario = {
        "scenario_type": "upper_shadow",
        "code": norm,
        "name": name,
        "setup_date": setup.isoformat(),
        "eval_from": eval_from,
        "eval_until": eval_until,
        "session_high": round(float(session_high), 2),
        "session_close": round(float(session_close), 2),
        "session_low": round(float(session_low), 2),
        "upper_shadow_ratio": round(shadow / span, 4),
        "bearish": {
            "condition": "break_below_session_low",
            "level": round(float(session_low), 2),
            "label": "低开低走跌破今日低点，确认短期见顶",
        },
        "bullish": {
            "condition": "gap_reclaim_high",
            "level": round(float(session_high), 2),
            "label": "高开反包则上影线为洗盘",
        },
        "status": "pending",
        "note": note.strip(),
    }
    rows = load_scenarios(path)
    key = _scenario_key(norm, setup.isoformat())
    rows = [row for row in rows if _scenario_key(str(row.get("code") or ""), str(row.get("setup_date") or "")) != key]
    rows.append(scenario)
    save_scenarios(rows, path)

    try:
        from agent_reach.daily_run.storage.hooks import on_l2_scenario

        on_l2_scenario(
            "technical_watch",
            key,
            scenario,
            code=norm,
            at=setup.isoformat(),
            title=f"{name} 长上影情景",
            content=(
                f"高 {scenario['session_high']} 收 {scenario['session_close']} 低 {scenario['session_low']}；"
                f"周一<{scenario['session_low']}见顶，反包>{scenario['session_high']}洗盘"
            ),
            dedupe_key=f"l2:technical_watch:{key}",
        )
    except Exception:
        pass
    return scenario


def _session_stats(
    session_scans: Optional[list[dict[str, Any]]],
    snapshot: dict[str, Any],
    code: str,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    norm = _normalize_code(code)
    prices: list[float] = []
    for scan in session_scans or []:
        if norm and _normalize_code(str(scan.get("code") or "")) not in ("", norm):
            continue
        price = scan.get("price")
        if price is not None:
            try:
                prices.append(float(price))
            except (TypeError, ValueError):
                pass
    for key in ("day_high", "price"):
        val = snapshot.get(key)
        if val is not None:
            try:
                prices.append(float(val))
            except (TypeError, ValueError):
                pass
    lows: list[float] = []
    for key in ("day_low", "price"):
        val = snapshot.get(key)
        if val is not None:
            try:
                lows.append(float(val))
            except (TypeError, ValueError):
                pass
    for scan in session_scans or []:
        if norm and _normalize_code(str(scan.get("code") or "")) not in ("", norm):
            continue
        price = scan.get("price")
        if price is not None:
            try:
                lows.append(float(price))
            except (TypeError, ValueError):
                pass
    close = snapshot.get("price")
    try:
        close_f = float(close) if close is not None else None
    except (TypeError, ValueError):
        close_f = None
    if not prices:
        return None, close_f, min(lows) if lows else close_f
    return max(prices), close_f, min(lows) if lows else close_f


def maybe_register_upper_shadow_from_session(
    *,
    code: str,
    name: str,
    snapshot: dict[str, Any],
    session_scans: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
    setup_date: Optional[str] = None,
    path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    cfg = technical_watch_cfg(settings)
    if not cfg.get("enabled", True):
        return None
    session_high, session_close, session_low = _session_stats(session_scans, snapshot, code)
    if session_high is None or session_close is None or session_low is None:
        return None
    if session_high <= session_close * 1.01:
        return None
    shadow = session_high - max(session_close, session_low)
    span = max(session_high - session_low, 0.01)
    if shadow / span < float(cfg["min_upper_shadow_ratio"]):
        return None
    change_pct = snapshot.get("change_pct")
    if change_pct is not None and float(change_pct) < float(cfg["min_spike_pct"]):
        return None
    day = setup_date or today_shanghai().isoformat()
    return register_upper_shadow_scenario(
        code=code,
        name=name,
        setup_date=day,
        session_high=session_high,
        session_close=session_close,
        session_low=session_low,
        settings=settings,
        path=path,
        note=f"盘中冲高 {session_high:.2f} 回落至 {session_close:.2f}，长上影待周一验证",
    )


def _active_scenarios(
    *,
    code: str = "",
    as_of: Optional[date] = None,
    path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    day = as_of or today_shanghai()
    out: list[dict[str, Any]] = []
    for row in load_scenarios(path):
        if str(row.get("status") or "pending") != "pending":
            continue
        try:
            eval_from = date.fromisoformat(str(row.get("eval_from") or "")[:10])
            eval_until = date.fromisoformat(str(row.get("eval_until") or "")[:10])
        except ValueError:
            continue
        if day < eval_from or day > eval_until:
            continue
        if code and _normalize_code(str(row.get("code") or "")) != _normalize_code(code):
            continue
        out.append(row)
    return out


def evaluate_scenario(
    scenario: dict[str, Any],
    *,
    price: Optional[float],
    change_pct: Optional[float] = None,
    open_price: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = technical_watch_cfg(settings)
    code = str(scenario.get("code") or "")
    name = str(scenario.get("name") or code)
    session_high = float(scenario.get("session_high") or 0)
    session_close = float(scenario.get("session_close") or 0)
    session_low = float(scenario.get("session_low") or 0)
    bear_level = float((scenario.get("bearish") or {}).get("level") or session_low)
    bull_level = float((scenario.get("bullish") or {}).get("level") or session_high)
    reclaim_tol = float(cfg["reclaim_high_tolerance_pct"]) / 100.0
    gap_up = float(cfg["gap_up_pct"]) / 100.0

    result: dict[str, Any] = {
        "code": code,
        "name": name,
        "scenario": scenario,
        "price": price,
        "change_pct": change_pct,
        "status": "pending",
        "headline": "",
        "action_hint": "观望",
    }
    if price is None:
        result["headline"] = (
            f"{name} 长上影后续：待验证跌破 {bear_level:.2f} 见顶 / 反包 {bull_level:.2f} 洗盘"
        )
        return result

    px = float(price)
    if px < bear_level:
        result.update(
            {
                "status": "bearish_confirmed",
                "headline": (
                    f"{name} 长上影后续：已跌破 {bear_level:.2f}（/setup 低 {session_low:.2f}），"
                    "确认短期见顶"
                ),
                "action_hint": "回避加仓，持仓考虑减仓",
            }
        )
        return result

    open_px = float(open_price) if open_price is not None else px
    gap_vs_close = (open_px - session_close) / session_close if session_close > 0 else 0.0
    reclaim = px >= bull_level * (1.0 - reclaim_tol)
    strong_day = change_pct is not None and float(change_pct) >= float(cfg["min_spike_pct"])
    if reclaim or (gap_vs_close >= gap_up and px >= session_close and strong_day):
        result.update(
            {
                "status": "bullish_washout",
                "headline": (
                    f"{name} 长上影后续：{'反包' if reclaim else '高开走强'}"
                    f"（现价 {px:.2f}），上影线倾向洗盘"
                ),
                "action_hint": "可观察回踩后承接，勿盲目追高",
            }
        )
        return result

    result["headline"] = (
        f"{name} 长上影后续：现价 {px:.2f} 介于 {bear_level:.2f}–{bull_level:.2f}，"
        f"跌破低点见顶 / 反包高点洗盘"
    )
    return result


def evaluate_active_scenarios(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    as_of: Optional[date] = None,
    path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    code = str(snapshot.get("code") or "")
    price = snapshot.get("price")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    change_pct = snapshot.get("change_pct")
    try:
        chg_f = float(change_pct) if change_pct is not None else None
    except (TypeError, ValueError):
        chg_f = None
    open_price = snapshot.get("open") or snapshot.get("open_price")
    results = [
        evaluate_scenario(
            row,
            price=price_f,
            change_pct=chg_f,
            open_price=open_price,
            settings=settings,
        )
        for row in _active_scenarios(code=code, as_of=as_of, path=path)
    ]
    return results


def _persist_scenario_status(
    scenario: dict[str, Any],
    status: str,
    *,
    path: Optional[Path] = None,
) -> None:
    rows = load_scenarios(path)
    key = _scenario_key(str(scenario.get("code") or ""), str(scenario.get("setup_date") or ""))
    updated: list[dict[str, Any]] = []
    for row in rows:
        if _scenario_key(str(row.get("code") or ""), str(row.get("setup_date") or "")) == key:
            row = {**row, "status": status}
            scenario.update(row)
        updated.append(row)
    save_scenarios(updated, path)


def technical_scenario_harness_evidence(
    evaluations: list[dict[str, Any]],
    *,
    path: Optional[Path] = None,
) -> dict[str, list[str]]:
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []
    for item in evaluations:
        status = str(item.get("status") or "pending")
        headline = str(item.get("headline") or "")
        name = item.get("name") or item.get("code")
        if status == "bearish_confirmed":
            memory.append(f"卖晚了：{headline}")
            policy.append(f"{name} 长上影跌破 setup 低点，短期见顶，profit_lock 优先锁利")
            plan.append(f"intraday：{name} 反弹至 MA20 附近分批减仓")
            _persist_scenario_status(item["scenario"], "bearish_confirmed", path=path)
        elif status == "bullish_washout":
            playbook.append(headline)
            plan.append(f"intraday：{name} 洗盘确认，观察回踩 {item['scenario'].get('session_close')} 承接")
            _persist_scenario_status(item["scenario"], "bullish_washout", path=path)
        elif headline:
            plan.append(headline)
    return {"memory": memory, "policy": policy, "playbook": playbook, "plan": plan}


def format_technical_scenario_markdown(evaluations: list[dict[str, Any]]) -> str:
    lines = [item.get("headline") for item in evaluations if item.get("headline")]
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"**📐 技术情景跟踪**\n\n{body}"
