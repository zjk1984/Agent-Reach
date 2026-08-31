# -*- coding: utf-8 -*-
"""Technical scenario watch — upper-shadow and limit-up shrink-pullback follow-ups."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import next_trading_day, today_shanghai


SYSTEM_MSS_CODE = "SYSTEM"


def technical_watch_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("technical_watch") or {})
    shrink = dict(block.get("limit_up_shrink_pullback") or {})
    liquidity = dict(block.get("liquidity_shrink") or {})
    mss_trend = dict(block.get("mss_trend") or {})
    cash_cap = dict(block.get("min_cash_ratio_cap") or {})
    return {
        "enabled": block.get("enabled", True),
        "min_upper_shadow_ratio": float(block.get("min_upper_shadow_ratio", 0.35)),
        "min_spike_pct": float(block.get("min_spike_pct", 3.0)),
        "eval_days": int(block.get("eval_days", 5)),
        "reclaim_high_tolerance_pct": float(block.get("reclaim_high_tolerance_pct", 1.5)),
        "gap_up_pct": float(block.get("gap_up_pct", 1.0)),
        "limit_up_shrink_pullback": {
            "enabled": shrink.get("enabled", True),
            "max_volume_ratio": float(shrink.get("max_volume_ratio", 0.85)),
            "min_pullback_pct": float(shrink.get("min_pullback_pct", -1.0)),
            "support_round_to": int(shrink.get("support_round_to", 10)),
            "support_tolerance_pct": float(shrink.get("support_tolerance_pct", 2.5)),
            "bearish_volume_ratio": float(shrink.get("bearish_volume_ratio", 1.1)),
            "open_near_prior_tolerance_pct": float(shrink.get("open_near_prior_tolerance_pct", 2.0)),
        },
        "liquidity_shrink": {
            "enabled": liquidity.get("enabled", True),
            "max_turnover_cny": float(liquidity.get("max_turnover_cny", 200_000_000)),
            "max_volume_ratio": float(liquidity.get("max_volume_ratio", 0.85)),
            "max_turnover_rate_pct": float(liquidity.get("max_turnover_rate_pct", 1.5)),
            "recovery_turnover_multiplier": float(liquidity.get("recovery_turnover_multiplier", 1.5)),
            "recovery_volume_ratio": float(liquidity.get("recovery_volume_ratio", 1.0)),
            "shrink_turnover_multiplier": float(liquidity.get("shrink_turnover_multiplier", 0.85)),
        },
        "mss_trend": {
            "enabled": mss_trend.get("enabled", True),
            "warning_level": float(mss_trend.get("warning_level", 50.0)),
            "bearish_level": float(mss_trend.get("bearish_level", 45.0)),
            "bullish_level": float(mss_trend.get("bullish_level", 55.0)),
            "scan_id": str(mss_trend.get("scan_id", "S12")),
            "scope": str(mss_trend.get("scope", "holdings")),
        },
        "min_cash_ratio_cap": {
            "enabled": cash_cap.get("enabled", True),
            "register_min_cash_ratio": float(cash_cap.get("register_min_cash_ratio", 0.5)),
            "relax_delta": float(cash_cap.get("relax_delta", 0.02)),
            "rebound_mss_level": float(cash_cap.get("rebound_mss_level", 55.0)),
        },
    }


def _is_system_scenario(row: dict[str, Any]) -> bool:
    return str(row.get("code") or "").upper() == SYSTEM_MSS_CODE


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


def _scenario_key(code: str, setup_date: str, scenario_type: str = "upper_shadow") -> str:
    return f"{_normalize_code(code)}/{str(setup_date)[:10]}/{scenario_type}"


def _row_key(row: dict[str, Any]) -> str:
    return _scenario_key(
        str(row.get("code") or ""),
        str(row.get("setup_date") or ""),
        str(row.get("scenario_type") or "upper_shadow"),
    )


def _eval_window(
    setup_date: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    cfg = technical_watch_cfg(settings)
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from_d = next_trading_day(setup, settings=settings)
    eval_from = eval_from_d.isoformat()
    eval_until = (eval_from_d + timedelta(days=max(1, cfg["eval_days"]))).isoformat()
    return eval_from, eval_until


def _save_scenario_row(
    scenario: dict[str, Any],
    *,
    path: Optional[Path] = None,
    l2_title: str = "",
    l2_content: str = "",
) -> dict[str, Any]:
    rows = load_scenarios(path)
    key = _row_key(scenario)
    rows = [row for row in rows if _row_key(row) != key]
    rows.append(scenario)
    save_scenarios(rows, path)
    try:
        from agent_reach.daily_run.storage.hooks import on_l2_scenario

        on_l2_scenario(
            "technical_watch",
            key,
            scenario,
            code=str(scenario.get("code") or ""),
            at=str(scenario.get("setup_date") or "")[:10],
            title=l2_title or f"{scenario.get('name')} 技术情景",
            content=l2_content or str(scenario.get("note") or ""),
            dedupe_key=f"l2:technical_watch:{key}",
        )
    except Exception:
        pass
    return scenario


def _price_tick(price: float) -> float:
    """Round-down step sized to the symbol price (avoid decade floors on mid/small caps)."""
    p = float(price)
    if p >= 200:
        return 10.0
    if p >= 20:
        return 1.0
    if p >= 5:
        return 0.5
    return 0.1


def _format_price_level(price: float) -> str:
    p = float(price)
    if p >= 100:
        return f"{p:.0f}"
    if p >= 10:
        return f"{p:.1f}".rstrip("0").rstrip(".")
    return f"{p:.2f}".rstrip("0").rstrip(".")


def _default_support_level(session_low: float, *, round_to: int = 10) -> float:
    low = float(session_low)
    if low <= 0:
        return 0.0
    step = _price_tick(low)
    if low >= 100 and int(round_to) >= 10:
        step = max(step, float(int(round_to)))
    support = math.floor(low / step) * step
    if support <= 0:
        support = step
    decimals = 2 if step < 1 else 1 if step < 10 else 0
    return round(support, decimals)


def _normalize_support_level(
    session_low: float,
    session_close: float,
    support_level: Optional[float],
    *,
    round_to: int = 10,
) -> float:
    """Pick a near-term support anchored on session low, not arbitrary decade floors."""
    low = float(session_low)
    close = float(session_close)
    derived = _default_support_level(low, round_to=round_to) if low > 0 else round(close, 2)
    if derived <= 0 and close > 0:
        derived = round(close, 2)
    if support_level is None:
        return derived
    support = float(support_level)
    if support <= 0:
        return derived
    if low > 0 and support < low * 0.97:
        return derived
    if close > 0 and support < close * 0.85:
        return derived
    return round(support, 2)


def _support_stabilize_label(support: float) -> str:
    return f"在 {_format_price_level(support)} 元附近缩量企稳"


def _resolve_scenario_support(
    scenario: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> float:
    shrink_cfg = technical_watch_cfg(settings)["limit_up_shrink_pullback"]
    session_low = float(scenario.get("session_low") or 0)
    session_close = float(scenario.get("session_close") or 0)
    raw = scenario.get("support_level")
    if raw is None:
        raw = (scenario.get("bullish") or {}).get("level")
    try:
        support_raw = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        support_raw = None
    return _normalize_support_level(
        session_low,
        session_close,
        support_raw,
        round_to=int(shrink_cfg["support_round_to"]),
    )


def _format_turnover_yi(turnover: float) -> str:
    return f"{float(turnover) / 1e8:.2f}亿"


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
    eval_from, eval_until = _eval_window(setup.isoformat(), settings=settings)
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
    return _save_scenario_row(
        scenario,
        path=path,
        l2_title=f"{name} 长上影情景",
        l2_content=(
            f"高 {scenario['session_high']} 收 {scenario['session_close']} 低 {scenario['session_low']}；"
            f"周一<{scenario['session_low']}见顶，反包>{scenario['session_high']}洗盘"
        ),
    )


def register_limit_up_shrink_pullback_scenario(
    *,
    code: str,
    name: str,
    setup_date: str,
    prior_close: float,
    session_close: float,
    session_low: float,
    session_high: float,
    support_level: Optional[float] = None,
    prior_day_change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
    note: str = "",
) -> dict[str, Any]:
    """Persist a limit-up-then-shrink-volume pullback scenario for follow-up."""
    cfg = technical_watch_cfg(settings)
    shrink_cfg = cfg["limit_up_shrink_pullback"]
    norm = _normalize_code(code)
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from, eval_until = _eval_window(setup.isoformat(), settings=settings)
    support = _normalize_support_level(
        session_low,
        session_close,
        support_level,
        round_to=int(shrink_cfg["support_round_to"]),
    )
    support_label = _format_price_level(support)
    scenario = {
        "scenario_type": "limit_up_shrink_pullback",
        "code": norm,
        "name": name,
        "setup_date": setup.isoformat(),
        "eval_from": eval_from,
        "eval_until": eval_until,
        "prior_close": round(float(prior_close), 2),
        "session_high": round(float(session_high), 2),
        "session_close": round(float(session_close), 2),
        "session_low": round(float(session_low), 2),
        "support_level": support,
        "prior_day_change_pct": round(float(prior_day_change_pct), 2)
        if prior_day_change_pct is not None
        else None,
        "setup_volume_ratio": round(float(volume_ratio), 2) if volume_ratio is not None else None,
        "bearish": {
            "condition": "volume_expansion_breakdown",
            "level": support,
            "label": "继续放量下跌，调整空间打开",
        },
        "bullish": {
            "condition": "hold_near_support",
            "level": support,
            "label": _support_stabilize_label(support),
        },
        "status": "pending",
        "note": note.strip(),
    }
    return _save_scenario_row(
        scenario,
        path=path,
        l2_title=f"{name} 涨停后缩量回调",
        l2_content=(
            f"昨收 {scenario['prior_close']} 涨停后今日收 {scenario['session_close']}；"
            f"周一关注 {support_label} 元附近企稳，放量跌破则调整空间打开"
        ),
    )


def register_liquidity_shrink_scenario(
    *,
    code: str,
    name: str,
    setup_date: str,
    session_close: float,
    session_low: float,
    turnover: float,
    turnover_rate: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
    note: str = "",
) -> dict[str, Any]:
    """Persist a low-liquidity shrink-volume watch scenario."""
    norm = _normalize_code(code)
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from, eval_until = _eval_window(setup.isoformat(), settings=settings)
    turnover_f = round(float(turnover), 2)
    scenario = {
        "scenario_type": "liquidity_shrink",
        "code": norm,
        "name": name,
        "setup_date": setup.isoformat(),
        "eval_from": eval_from,
        "eval_until": eval_until,
        "session_close": round(float(session_close), 2),
        "session_low": round(float(session_low), 2),
        "setup_turnover": turnover_f,
        "setup_turnover_rate": round(float(turnover_rate), 2)
        if turnover_rate is not None
        else None,
        "setup_volume_ratio": round(float(volume_ratio), 2) if volume_ratio is not None else None,
        "bearish": {
            "condition": "liquidity_shrink_trim",
            "level": turnover_f,
            "label": "流动性持续萎缩，关注被进一步减仓",
        },
        "bullish": {
            "condition": "liquidity_recovery",
            "level": turnover_f,
            "label": "成交额恢复且排查无基本面恶化",
        },
        "status": "pending",
        "note": note.strip(),
    }
    turnover_label = _format_turnover_yi(turnover_f)
    return _save_scenario_row(
        scenario,
        path=path,
        l2_title=f"{name} 流动性萎缩",
        l2_content=(
            f"成交额 {turnover_label} 持续缩量；"
            "关注基本面变化及是否被进一步减仓"
        ),
    )


def collect_scan_mss_range(
    symbols: list[str],
    *,
    scan_id: str = "S12",
    settings: Optional[dict[str, Any]] = None,
) -> tuple[Optional[float], Optional[float], str]:
    """Return min/max MSS at a scan id across symbols (fallback: last scan)."""
    from agent_reach.daily_run.intraday import load_state

    wanted = str(scan_id or "S12")
    values: list[float] = []
    used_scan = wanted
    for code in symbols:
        norm = _normalize_code(code)
        if not norm:
            continue
        state = load_state(code=norm)
        scans = list(state.scans or [])
        matched = next((s for s in scans if str(s.get("scan_id") or "") == wanted), None)
        if matched is None and scans:
            matched = scans[-1]
            used_scan = str(matched.get("scan_id") or wanted)
        if not matched:
            continue
        mss = matched.get("mss_final")
        if mss is None:
            continue
        try:
            values.append(float(mss))
        except (TypeError, ValueError):
            pass
    if not values:
        return None, None, used_scan
    return round(min(values), 2), round(max(values), 2), used_scan


def register_mss_trend_scenario(
    *,
    setup_date: str,
    mss_low: float,
    mss_high: float,
    mss_scan_id: str = "S12",
    warning_level: float = 50.0,
    bearish_level: float = 45.0,
    bullish_level: float = 55.0,
    settings: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
    note: str = "",
) -> dict[str, Any]:
    """Persist portfolio MSS trend follow-up (system-level scenario)."""
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from, eval_until = _eval_window(setup.isoformat(), settings=settings)
    scenario = {
        "scenario_type": "mss_trend",
        "code": SYSTEM_MSS_CODE,
        "name": "量化系统MSS",
        "setup_date": setup.isoformat(),
        "eval_from": eval_from,
        "eval_until": eval_until,
        "mss_scan_id": str(mss_scan_id or "S12"),
        "setup_mss_low": round(float(mss_low), 2),
        "setup_mss_high": round(float(mss_high), 2),
        "warning_level": round(float(warning_level), 2),
        "bearish": {
            "condition": "mss_below_bearish",
            "level": round(float(bearish_level), 2),
            "label": f"MSS 继续下行至 {bearish_level:.0f} 以下，触发更深层防御",
        },
        "bullish": {
            "condition": "mss_above_bullish",
            "level": round(float(bullish_level), 2),
            "label": f"MSS 反弹回 {bullish_level:.0f} 以上，防御解除",
        },
        "status": "pending",
        "note": note.strip(),
    }
    return _save_scenario_row(
        scenario,
        path=path,
        l2_title="量化系统 MSS 走向",
        l2_content=(
            f"{mss_scan_id} MSS {mss_low:.1f}~{mss_high:.1f} 跌破 {warning_level:.0f}；"
            f"周一<{bearish_level:.0f} 深层防御 / >{bullish_level:.0f} 防御解除"
        ),
    )


def maybe_register_mss_trend_from_session(
    *,
    symbols: list[str],
    settings: Optional[dict[str, Any]] = None,
    setup_date: Optional[str] = None,
    path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    cfg = technical_watch_cfg(settings)
    mss_cfg = cfg["mss_trend"]
    if not cfg.get("enabled", True) or not mss_cfg.get("enabled", True):
        return None

    from agent_reach.daily_run.symbols import list_target_symbols, portfolio_from_snapshot

    scope = str(mss_cfg.get("scope") or "holdings")
    if scope == "holdings":
        pf_codes = list_target_symbols(
            {"holdings": [{"code": c} for c in symbols], "watchlist": []},
            mode="holdings",
        )
        target_codes = pf_codes
    else:
        target_codes = list(symbols)
    if not target_codes:
        return None

    scan_id = str(mss_cfg.get("scan_id") or "S12")
    mss_low, mss_high, used_scan = collect_scan_mss_range(
        target_codes,
        scan_id=scan_id,
        settings=settings,
    )
    if mss_low is None or mss_high is None:
        return None

    warning = float(mss_cfg["warning_level"])
    if mss_low >= warning:
        return None

    bearish = float(mss_cfg["bearish_level"])
    bullish = float(mss_cfg["bullish_level"])
    day = setup_date or today_shanghai().isoformat()
    return register_mss_trend_scenario(
        setup_date=day,
        mss_low=mss_low,
        mss_high=mss_high,
        mss_scan_id=used_scan,
        warning_level=warning,
        bearish_level=bearish,
        bullish_level=bullish,
        settings=settings,
        path=path,
        note=(
            f"今日 MSS 已跌破 {warning:.0f}（{used_scan}: {mss_low:.1f}~{mss_high:.1f}）；"
            f"若下周一继续下行至 {bearish:.0f} 以下可能触发更深层防御，"
            f"反弹回 {bullish:.0f} 以上则防御解除"
        ),
    )


def register_min_cash_ratio_cap_scenario(
    *,
    setup_date: str,
    min_cash_ratio: float,
    cash_ratio: Optional[float],
    baseline_min_cash_ratio: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
    note: str = "",
) -> dict[str, Any]:
    """Persist min_cash_ratio harness cap — rally miss / threshold callback watch."""
    setup = date.fromisoformat(str(setup_date)[:10])
    eval_from, eval_until = _eval_window(setup.isoformat(), settings=settings)
    cap_cfg = technical_watch_cfg(settings)["min_cash_ratio_cap"]
    min_cash = round(float(min_cash_ratio), 4)
    cash = round(float(cash_ratio), 4) if cash_ratio is not None else None
    baseline = (
        round(float(baseline_min_cash_ratio), 4)
        if baseline_min_cash_ratio is not None
        else None
    )
    scenario = {
        "scenario_type": "min_cash_ratio_cap",
        "code": SYSTEM_MSS_CODE,
        "name": "量化系统现金比例",
        "setup_date": setup.isoformat(),
        "eval_from": eval_from,
        "eval_until": eval_until,
        "setup_min_cash_ratio": min_cash,
        "baseline_min_cash_ratio": baseline,
        "setup_cash_ratio": cash,
        "rebound_mss_level": float(cap_cfg["rebound_mss_level"]),
        "bearish": {
            "condition": "rally_miss_on_cash_cap",
            "level": min_cash,
            "label": "市场反弹时现金比例限制可能踏空",
        },
        "bullish": {
            "condition": "min_cash_threshold_relaxed",
            "level": min_cash,
            "label": "harness 回调 min_cash 阈值后可加仓",
        },
        "status": "pending",
        "note": note.strip(),
    }
    cash_s = f"{cash:.0%}" if cash is not None else "—"
    return _save_scenario_row(
        scenario,
        path=path,
        l2_title="min_cash_ratio 半仓约束",
        l2_content=(
            f"min_cash {min_cash:.0%} / 当前现金 {cash_s}；"
            "关注反弹踏空与 harness 阈值回调"
        ),
    )


def maybe_register_min_cash_ratio_cap_from_session(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    setup_date: Optional[str] = None,
    path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    cfg = technical_watch_cfg(settings)
    cap_cfg = cfg["min_cash_ratio_cap"]
    if not cfg.get("enabled", True) or not cap_cfg.get("enabled", True):
        return None

    from agent_reach.daily_run.harness_policy import min_cash_ratio_base, min_cash_ratio_default
    from agent_reach.daily_run.symbols import portfolio_from_snapshot

    effective = float(min_cash_ratio_default(settings or {}))
    register_floor = float(cap_cfg["register_min_cash_ratio"])
    if effective + 1e-9 < register_floor:
        return None

    pf = portfolio_from_snapshot(snapshot)
    cash_ratio = pf.get("cash_ratio")
    if cash_ratio is None:
        cash_ratio = (snapshot.get("portfolio") or {}).get("cash_ratio")
    try:
        cash_f = float(cash_ratio) if cash_ratio is not None else None
    except (TypeError, ValueError):
        cash_f = None

    thresholds = (settings or {}).get("thresholds") or {}
    baseline = min_cash_ratio_base(settings or {}, thresholds)

    day = setup_date or today_shanghai().isoformat()
    cash_label = f"{cash_f:.0%}" if cash_f is not None else "—"
    return register_min_cash_ratio_cap_scenario(
        setup_date=day,
        min_cash_ratio=effective,
        cash_ratio=cash_f,
        baseline_min_cash_ratio=baseline,
        settings=settings,
        path=path,
        note=(
            f"min_cash_ratio {effective:.0%} 要求半仓现金（当前 {cash_label}）；"
            "若下周一市场反弹，系统可能因现金比例限制踏空；关注 harness 阈值回调"
        ),
    )


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


def maybe_register_limit_up_shrink_pullback_from_session(
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
    shrink_cfg = cfg["limit_up_shrink_pullback"]
    if not cfg.get("enabled", True) or not shrink_cfg.get("enabled", True):
        return None

    session_high, session_close, session_low = _session_stats(session_scans, snapshot, code)
    if session_high is None or session_close is None or session_low is None:
        return None

    change_pct = snapshot.get("change_pct")
    try:
        chg = float(change_pct) if change_pct is not None else None
    except (TypeError, ValueError):
        chg = None
    if chg is None or chg > float(shrink_cfg["min_pullback_pct"]):
        return None

    volume_ratio = snapshot.get("volume_ratio")
    try:
        vol_ratio = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        vol_ratio = None
    if vol_ratio is not None and vol_ratio > float(shrink_cfg["max_volume_ratio"]):
        return None

    prior_close = snapshot.get("reference_price") or snapshot.get("prior_close")
    try:
        prior = float(prior_close) if prior_close is not None else None
    except (TypeError, ValueError):
        prior = None
    if prior is None or prior <= 0:
        return None

    open_tol = float(shrink_cfg["open_near_prior_tolerance_pct"]) / 100.0
    if abs(session_high - prior) / prior > open_tol:
        return None

    from agent_reach.daily_run.tradability import board_limit_pct, price_limit_state

    prior_day_change = snapshot.get("prior_day_change_pct")
    try:
        prior_day_change_f = float(prior_day_change) if prior_day_change is not None else None
    except (TypeError, ValueError):
        prior_day_change_f = None
    limit_pct = board_limit_pct(code, name)
    if prior_day_change_f is not None:
        if price_limit_state(prior_day_change_f, limit_pct) != "limit_up":
            return None

    day = setup_date or today_shanghai().isoformat()
    support = _default_support_level(
        session_low,
        round_to=int(shrink_cfg["support_round_to"]),
    )
    return register_limit_up_shrink_pullback_scenario(
        code=code,
        name=name,
        setup_date=day,
        prior_close=prior,
        session_close=session_close,
        session_low=session_low,
        session_high=session_high,
        support_level=support,
        prior_day_change_pct=prior_day_change_f,
        volume_ratio=vol_ratio,
        settings=settings,
        path=path,
        note=(
            f"昨收 {prior:.2f} 涨停后今日缩量回落至 {session_close:.2f}；"
            f"周一关注 {_format_price_level(support)} 元附近企稳，放量跌破则调整空间打开"
        ),
    )


def maybe_register_liquidity_shrink_from_session(
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
    liq_cfg = cfg["liquidity_shrink"]
    if not cfg.get("enabled", True) or not liq_cfg.get("enabled", True):
        return None

    _session_high, session_close, session_low = _session_stats(session_scans, snapshot, code)
    if session_close is None or session_low is None:
        return None

    turnover = snapshot.get("turnover")
    try:
        turnover_f = float(turnover) if turnover is not None else None
    except (TypeError, ValueError):
        turnover_f = None
    if turnover_f is None or turnover_f <= 0:
        return None
    if turnover_f > float(liq_cfg["max_turnover_cny"]):
        return None

    volume_ratio = snapshot.get("volume_ratio")
    try:
        vol_ratio = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        vol_ratio = None

    turnover_rate = snapshot.get("turnover_rate")
    try:
        turnover_rate_f = float(turnover_rate) if turnover_rate is not None else None
    except (TypeError, ValueError):
        turnover_rate_f = None

    low_liquidity = False
    if vol_ratio is not None and vol_ratio <= float(liq_cfg["max_volume_ratio"]):
        low_liquidity = True
    if turnover_rate_f is not None and turnover_rate_f <= float(liq_cfg["max_turnover_rate_pct"]):
        low_liquidity = True
    if vol_ratio is None and turnover_rate_f is None:
        low_liquidity = True
    if not low_liquidity:
        return None

    day = setup_date or today_shanghai().isoformat()
    turnover_label = _format_turnover_yi(turnover_f)
    return register_liquidity_shrink_scenario(
        code=code,
        name=name,
        setup_date=day,
        session_close=session_close,
        session_low=session_low,
        turnover=turnover_f,
        turnover_rate=turnover_rate_f,
        volume_ratio=vol_ratio,
        settings=settings,
        path=path,
        note=(
            f"成交额仅 {turnover_label}，持续缩量；"
            "关注是否有基本面变化或被进一步减仓"
        ),
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
        if code and not _is_system_scenario(row):
            row_code = _normalize_code(str(row.get("code") or ""))
            if row_code != _normalize_code(code):
                continue
        out.append(row)
    return out


def evaluate_scenario(
    scenario: dict[str, Any],
    *,
    price: Optional[float] = None,
    change_pct: Optional[float] = None,
    open_price: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    turnover: Optional[float] = None,
    mss: Optional[float] = None,
    min_cash_ratio: Optional[float] = None,
    cash_ratio: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    scenario_type = str(scenario.get("scenario_type") or "upper_shadow")
    if scenario_type == "limit_up_shrink_pullback":
        return _evaluate_limit_up_shrink_pullback(
            scenario,
            price=price,
            change_pct=change_pct,
            volume_ratio=volume_ratio,
            settings=settings,
        )
    if scenario_type == "liquidity_shrink":
        return _evaluate_liquidity_shrink(
            scenario,
            price=price,
            change_pct=change_pct,
            volume_ratio=volume_ratio,
            turnover=turnover,
            settings=settings,
        )
    if scenario_type == "mss_trend":
        return _evaluate_mss_trend(
            scenario,
            mss=mss,
            settings=settings,
        )
    if scenario_type == "min_cash_ratio_cap":
        return _evaluate_min_cash_ratio_cap(
            scenario,
            min_cash_ratio=min_cash_ratio,
            cash_ratio=cash_ratio,
            mss=mss,
            settings=settings,
        )
    return _evaluate_upper_shadow(
        scenario,
        price=price,
        change_pct=change_pct,
        open_price=open_price,
        settings=settings,
    )


def _evaluate_upper_shadow(
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


def _evaluate_limit_up_shrink_pullback(
    scenario: dict[str, Any],
    *,
    price: Optional[float],
    change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = technical_watch_cfg(settings)
    shrink_cfg = cfg["limit_up_shrink_pullback"]
    code = str(scenario.get("code") or "")
    name = str(scenario.get("name") or code)
    support = _resolve_scenario_support(scenario, settings=settings)
    support_label = _format_price_level(support)
    setup_low = float(scenario.get("session_low") or 0)
    tol = float(shrink_cfg["support_tolerance_pct"]) / 100.0
    bear_vol = float(shrink_cfg["bearish_volume_ratio"])

    result: dict[str, Any] = {
        "code": code,
        "name": name,
        "scenario": scenario,
        "price": price,
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "status": "pending",
        "headline": "",
        "action_hint": "观望",
    }
    if price is None:
        result["headline"] = (
            f"{name} 涨停后缩量回调：关注 {support_label} 元附近企稳 / "
            "放量跌破则调整空间打开"
        )
        return result

    px = float(price)
    try:
        vol = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        vol = None
    try:
        chg = float(change_pct) if change_pct is not None else None
    except (TypeError, ValueError):
        chg = None

    lower = support * (1.0 - tol)
    upper = support * (1.0 + tol)
    volume_breakdown = vol is not None and vol >= bear_vol and (chg is None or chg < 0)
    if px < lower and (volume_breakdown or px < setup_low):
        result.update(
            {
                "status": "adjustment_open",
                "headline": (
                    f"{name} 涨停后回调：已跌破 {support_label} 元支撑"
                    f"{'且放量' if volume_breakdown else ''}，调整空间打开"
                ),
                "action_hint": "回避加仓，持仓考虑减仓",
            }
        )
        return result

    if lower <= px <= upper and not volume_breakdown:
        result.update(
            {
                "status": "support_holding",
                "headline": (
                    f"{name} 涨停后回调：现价 {px:.2f} 在 {support_label} 元附近企稳"
                ),
                "action_hint": "可观察承接，勿盲目杀跌",
            }
        )
        return result

    result["headline"] = (
        f"{name} 涨停后回调：现价 {px:.2f}，"
        f"关注 {support_label} 元附近企稳 / 放量跌破则调整空间打开"
    )
    return result


def _evaluate_liquidity_shrink(
    scenario: dict[str, Any],
    *,
    price: Optional[float],
    change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    turnover: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = technical_watch_cfg(settings)
    liq_cfg = cfg["liquidity_shrink"]
    code = str(scenario.get("code") or "")
    name = str(scenario.get("name") or code)
    setup_turnover = float(scenario.get("setup_turnover") or 0)
    setup_close = float(scenario.get("session_close") or 0)
    shrink_mult = float(liq_cfg["shrink_turnover_multiplier"])
    recovery_mult = float(liq_cfg["recovery_turnover_multiplier"])
    recovery_vol = float(liq_cfg["recovery_volume_ratio"])

    result: dict[str, Any] = {
        "code": code,
        "name": name,
        "scenario": scenario,
        "price": price,
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "turnover": turnover,
        "status": "pending",
        "headline": "",
        "action_hint": "观望",
    }
    turnover_label = _format_turnover_yi(setup_turnover)
    if price is None:
        result["headline"] = (
            f"{name} 流动性：setup 成交额 {turnover_label} 持续缩量，"
            "关注基本面变化及是否被进一步减仓"
        )
        return result

    try:
        vol = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        vol = None
    try:
        to = float(turnover) if turnover is not None else None
    except (TypeError, ValueError):
        to = None
    try:
        chg = float(change_pct) if change_pct is not None else None
    except (TypeError, ValueError):
        chg = None
    px = float(price)

    liquidity_recovered = (
        (to is not None and to >= setup_turnover * recovery_mult)
        or (vol is not None and vol >= recovery_vol)
    )
    if liquidity_recovered:
        result.update(
            {
                "status": "liquidity_recovered",
                "headline": (
                    f"{name} 流动性：成交额/量比回升"
                    f"（{'成交额恢复' if to and to >= setup_turnover * recovery_mult else '量比恢复'}），"
                    "仍需排查基本面"
                ),
                "action_hint": "流动性改善，继续跟踪基本面与持仓逻辑",
            }
        )
        return result

    still_shrinking = to is not None and to <= setup_turnover * shrink_mult
    price_weak = (chg is not None and chg < 0) or px < setup_close
    if still_shrinking and price_weak:
        result.update(
            {
                "status": "liquidity_trim_risk",
                "headline": (
                    f"{name} 流动性：成交额 {_format_turnover_yi(to)} 继续萎缩且价格走弱，"
                    "警惕被进一步减仓"
                ),
                "action_hint": "排查基本面变化，持仓考虑防御性减仓",
            }
        )
        return result

    result["headline"] = (
        f"{name} 流动性：setup 成交额 {turnover_label} 持续缩量，"
        "关注基本面变化及是否被进一步减仓"
    )
    return result


def _evaluate_mss_trend(
    scenario: dict[str, Any],
    *,
    mss: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = technical_watch_cfg(settings)
    mss_cfg = cfg["mss_trend"]
    name = str(scenario.get("name") or "量化系统MSS")
    setup_low = float(scenario.get("setup_mss_low") or 0)
    setup_high = float(scenario.get("setup_mss_high") or 0)
    scan_id = str(scenario.get("mss_scan_id") or "S12")
    warning = float(scenario.get("warning_level") or mss_cfg["warning_level"])
    bear_level = float((scenario.get("bearish") or {}).get("level") or mss_cfg["bearish_level"])
    bull_level = float((scenario.get("bullish") or {}).get("level") or mss_cfg["bullish_level"])

    result: dict[str, Any] = {
        "code": SYSTEM_MSS_CODE,
        "name": name,
        "scenario": scenario,
        "mss": mss,
        "status": "pending",
        "headline": "",
        "action_hint": "观望",
    }
    if mss is None:
        result["headline"] = (
            f"{name}：{scan_id} setup {setup_low:.1f}~{setup_high:.1f} 跌破 {warning:.0f}；"
            f"周一<{bear_level:.0f} 深层防御 / >{bull_level:.0f} 防御解除"
        )
        return result

    mss_f = float(mss)
    if mss_f < bear_level:
        result.update(
            {
                "status": "deeper_defense",
                "headline": (
                    f"{name}：MSS {mss_f:.1f} 跌破 {bear_level:.0f}，触发更深层防御"
                ),
                "action_hint": "宏观避险，优先 defensive_trim / 回避加仓",
            }
        )
        return result

    if mss_f > bull_level:
        result.update(
            {
                "status": "defense_released",
                "headline": (
                    f"{name}：MSS {mss_f:.1f} 回升至 {bull_level:.0f} 以上，防御解除"
                ),
                "action_hint": "可恢复常规 intraday 阈值，仍须验证 lookback",
            }
        )
        return result

    result["headline"] = (
        f"{name}：MSS {mss_f:.1f} 介于 {bear_level:.0f}–{bull_level:.0f}，"
        f"setup {setup_low:.1f}~{setup_high:.1f}，继续跟踪防御层级"
    )
    return result


def _evaluate_min_cash_ratio_cap(
    scenario: dict[str, Any],
    *,
    min_cash_ratio: Optional[float] = None,
    cash_ratio: Optional[float] = None,
    mss: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = technical_watch_cfg(settings)
    cap_cfg = cfg["min_cash_ratio_cap"]
    name = str(scenario.get("name") or "量化系统现金比例")
    setup_min = float(scenario.get("setup_min_cash_ratio") or 0)
    setup_cash = scenario.get("setup_cash_ratio")
    rebound_mss = float(scenario.get("rebound_mss_level") or cap_cfg["rebound_mss_level"])
    relax_delta = float(cap_cfg["relax_delta"])

    result: dict[str, Any] = {
        "code": SYSTEM_MSS_CODE,
        "name": name,
        "scenario": scenario,
        "min_cash_ratio": min_cash_ratio,
        "cash_ratio": cash_ratio,
        "mss": mss,
        "status": "pending",
        "headline": "",
        "action_hint": "观望",
    }
    setup_cash_s = (
        f"{float(setup_cash):.0%}" if setup_cash is not None else "—"
    )
    if min_cash_ratio is None and cash_ratio is None:
        result["headline"] = (
            f"{name}：min_cash {setup_min:.0%}（setup 现金 {setup_cash_s}）；"
            "关注反弹踏空与 harness 阈值回调"
        )
        return result

    try:
        effective_min = float(min_cash_ratio) if min_cash_ratio is not None else setup_min
    except (TypeError, ValueError):
        effective_min = setup_min
    try:
        cash_f = float(cash_ratio) if cash_ratio is not None else None
    except (TypeError, ValueError):
        cash_f = None
    try:
        mss_f = float(mss) if mss is not None else None
    except (TypeError, ValueError):
        mss_f = None

    if effective_min + 1e-9 < setup_min - relax_delta:
        result.update(
            {
                "status": "threshold_relaxed",
                "headline": (
                    f"{name}：min_cash 由 {setup_min:.0%} 回调至 {effective_min:.0%}，"
                    "现金约束放松可评估加仓"
                ),
                "action_hint": "复核 deploy 预算与 MSS，避免盲目追高",
            }
        )
        return result

    rebound = mss_f is not None and mss_f >= rebound_mss
    cash_blocked = cash_f is not None and cash_f + 1e-9 < effective_min
    if cash_blocked and (rebound or mss_f is None or mss_f >= 50.0):
        result.update(
            {
                "status": "rally_miss_risk",
                "headline": (
                    f"{name}：现金 {cash_f:.0%} < min_cash {effective_min:.0%}"
                    f"{'且 MSS 回暖' if rebound else ''}，反弹可能踏空"
                ),
                "action_hint": "关注 harness 是否回调 min_cash，或手动减仓腾现金",
            }
        )
        return result

    cash_label = f"{cash_f:.0%}" if cash_f is not None else "—"
    result["headline"] = (
        f"{name}：min_cash {effective_min:.0%} / 现金 {cash_label}；"
        "继续跟踪阈值回调"
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
    volume_ratio = snapshot.get("volume_ratio")
    try:
        vol_f = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        vol_f = None
    turnover = snapshot.get("turnover")
    try:
        turnover_f = float(turnover) if turnover is not None else None
    except (TypeError, ValueError):
        turnover_f = None
    mss_f: Optional[float] = None
    for key in ("mss_final", "lookback_mss"):
        raw_mss = snapshot.get(key)
        if raw_mss is not None:
            try:
                mss_f = float(raw_mss)
                break
            except (TypeError, ValueError):
                pass
    cfg = technical_watch_cfg(settings)
    mss_cfg = cfg["mss_trend"]
    if snapshot.get("portfolio"):
        from agent_reach.daily_run.symbols import list_target_symbols, portfolio_from_snapshot

        pf = portfolio_from_snapshot(snapshot)
        scope = str(mss_cfg.get("scope") or "holdings")
        mode = scope if scope in ("holdings", "all", "watchlist") else "holdings"
        scope_symbols = list_target_symbols(pf, mode=mode)
        low, _high, _sid = collect_scan_mss_range(
            scope_symbols,
            scan_id=str(mss_cfg.get("scan_id") or "S12"),
            settings=settings,
        )
        if low is not None:
            mss_f = low
    from agent_reach.daily_run.harness_policy import min_cash_ratio_default

    effective_min_cash = float(min_cash_ratio_default(settings or {}))
    cash_ratio_val: Optional[float] = None
    pf_block = snapshot.get("portfolio") or {}
    raw_cash = pf_block.get("cash_ratio")
    if raw_cash is None:
        from agent_reach.daily_run.symbols import portfolio_from_snapshot

        raw_cash = portfolio_from_snapshot(snapshot).get("cash_ratio")
    if raw_cash is not None:
        try:
            cash_ratio_val = float(raw_cash)
        except (TypeError, ValueError):
            cash_ratio_val = None
    results = [
        evaluate_scenario(
            row,
            price=price_f,
            change_pct=chg_f,
            open_price=open_price,
            volume_ratio=vol_f,
            turnover=turnover_f,
            mss=mss_f,
            min_cash_ratio=effective_min_cash,
            cash_ratio=cash_ratio_val,
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
    key = _row_key(scenario)
    updated: list[dict[str, Any]] = []
    for row in rows:
        if _row_key(row) == key:
            row = {**row, "status": status}
            scenario.update(row)
        updated.append(row)
    save_scenarios(updated, path)


def technical_scenario_harness_evidence(
    evaluations: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
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
        elif status == "adjustment_open":
            memory.append(headline)
            policy.append(f"{name} 涨停后回调跌破支撑，调整空间打开，防御减仓优先")
            plan.append(f"intraday：{name} 反弹至 MA20 附近分批减仓")
            _persist_scenario_status(item["scenario"], "adjustment_open", path=path)
        elif status == "support_holding":
            playbook.append(headline)
            support = _resolve_scenario_support(item["scenario"], settings=settings)
            plan.append(
                f"intraday：{name} 在 {_format_price_level(support)} 元附近企稳，观察承接"
            )
            _persist_scenario_status(item["scenario"], "support_holding", path=path)
        elif status == "liquidity_trim_risk":
            memory.append(headline)
            policy.append(f"{name} 流动性持续萎缩，排查基本面并优先考虑防御减仓")
            plan.append(f"intraday：{name} 低流动性下避免接飞刀，反弹减仓")
            _persist_scenario_status(item["scenario"], "liquidity_trim_risk", path=path)
        elif status == "liquidity_recovered":
            playbook.append(headline)
            plan.append(f"intraday：{name} 流动性回升，复核 thesis/watchlist intel")
            _persist_scenario_status(item["scenario"], "liquidity_recovered", path=path)
        elif status == "deeper_defense":
            memory.append(headline)
            policy.append(f"{name} 跌破防御线，macro_veto/defensive_trim 优先，回避加仓")
            plan.append("intraday：全持仓扫描 MSS，触发 defensive_trim 与 macro 回避")
            _persist_scenario_status(item["scenario"], "deeper_defense", path=path)
        elif status == "defense_released":
            playbook.append(headline)
            plan.append("intraday：MSS 防御解除，恢复常规 lookback 阈值")
            _persist_scenario_status(item["scenario"], "defense_released", path=path)
        elif status == "threshold_relaxed":
            playbook.append(headline)
            plan.append("intraday：min_cash 阈值回调，评估 deploy 预算与加仓窗口")
            _persist_scenario_status(item["scenario"], "threshold_relaxed", path=path)
        elif status == "rally_miss_risk":
            memory.append(f"踏空：{headline}")
            policy.append(f"{name} 现金比例低于 min_cash，反弹期关注 harness 阈值回调")
            plan.append("intraday：MSS 回暖但 buy_cash 阻断时，优先等 harness 放松 min_cash")
            _persist_scenario_status(item["scenario"], "rally_miss_risk", path=path)
        elif headline:
            plan.append(headline)
    return {"memory": memory, "policy": policy, "playbook": playbook, "plan": plan}


def format_technical_scenario_markdown(evaluations: list[dict[str, Any]]) -> str:
    lines = [item.get("headline") for item in evaluations if item.get("headline")]
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"**📐 技术情景跟踪**\n\n{body}"


def scenarios_for_setup_date(
    setup_date: str,
    *,
    path: Optional[Path] = None,
    pending_only: bool = True,
) -> list[dict[str, Any]]:
    day = str(setup_date)[:10]
    out: list[dict[str, Any]] = []
    for row in load_scenarios(path):
        if str(row.get("setup_date") or "")[:10] != day:
            continue
        if pending_only and str(row.get("status") or "pending") != "pending":
            continue
        out.append(row)
    out.sort(key=lambda row: str(row.get("code") or ""))
    return out


def format_close_technical_watch_markdown(
    scenarios: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    if not scenarios:
        return ""
    lines = ["**📐 技术情景跟踪（收盘登记）**", ""]
    for sc in scenarios:
        scenario_type = str(sc.get("scenario_type") or "upper_shadow")
        name = sc.get("name") or sc.get("code")
        code = sc.get("code") or ""
        eval_from = sc.get("eval_from")
        setup_date = str(sc.get("setup_date") or "")[:10]
        note = str(sc.get("note") or "").strip()

        if scenario_type == "limit_up_shrink_pullback":
            prior = sc.get("prior_close")
            close_px = sc.get("session_close")
            low = sc.get("session_low")
            support = _resolve_scenario_support(sc, settings=settings)
            bull_label = _support_stabilize_label(support)
            bear = sc.get("bearish") or {}
            bull = sc.get("bullish") or {}
            lines.append(f"- **{name} {code}** · 涨停后缩量回调（{setup_date}）")
            lines.append(f"  - 昨收 **{prior}** / 今收 **{close_px}** / 低 **{low}**")
            lines.append(f"  - 📍 **企稳**：{bull_label}")
            lines.append(
                f"  - 📉 **调整**：{bear.get('label') or '继续放量下跌，调整空间打开'}"
            )
        elif scenario_type == "liquidity_shrink":
            close_px = sc.get("session_close")
            low = sc.get("session_low")
            setup_turnover = sc.get("setup_turnover")
            turnover_label = _format_turnover_yi(float(setup_turnover or 0))
            turnover_rate = sc.get("setup_turnover_rate")
            vol_ratio = sc.get("setup_volume_ratio")
            bear = sc.get("bearish") or {}
            bull = sc.get("bullish") or {}
            lines.append(f"- **{name} {code}** · 流动性萎缩（{setup_date}）")
            lines.append(f"  - 收 **{close_px}** / 低 **{low}** / 成交额 **{turnover_label}**")
            if turnover_rate is not None:
                lines.append(f"  - 换手率 **{turnover_rate}%**")
            if vol_ratio is not None:
                lines.append(f"  - 量比 **{vol_ratio}**")
            lines.append(
                f"  - 🔍 **跟踪**：{bull.get('label') or '排查基本面变化、成交额是否恢复'}"
            )
            lines.append(
                f"  - ⚠️ **减仓**：{bear.get('label') or '流动性持续萎缩，警惕被进一步减仓'}"
            )
        elif scenario_type == "mss_trend":
            scan_id = sc.get("mss_scan_id") or "S12"
            low = sc.get("setup_mss_low")
            high = sc.get("setup_mss_high")
            warning = sc.get("warning_level")
            bear = sc.get("bearish") or {}
            bull = sc.get("bullish") or {}
            lines.append(f"- **{name}** · MSS 走向（{setup_date}）")
            lines.append(f"  - {scan_id} MSS **{low}~{high}**（已跌破 **{warning}**）")
            lines.append(f"  - 📉 **深层防御**：{bear.get('label')}")
            lines.append(f"  - 📈 **防御解除**：{bull.get('label')}")
        elif scenario_type == "min_cash_ratio_cap":
            min_cash = sc.get("setup_min_cash_ratio")
            cash = sc.get("setup_cash_ratio")
            baseline = sc.get("baseline_min_cash_ratio")
            bear = sc.get("bearish") or {}
            bull = sc.get("bullish") or {}
            cash_s = f"{float(cash):.0%}" if cash is not None else "—"
            base_s = f"{float(baseline):.0%}" if baseline is not None else "—"
            lines.append(f"- **{name}** · min_cash 约束（{setup_date}）")
            lines.append(
                f"  - harness **min_cash {float(min_cash):.0%}** / 当前现金 **{cash_s}**"
                f"（基准 {base_s}）"
            )
            lines.append(f"  - 📈 **回调**：{bull.get('label')}")
            lines.append(f"  - ⚠️ **踏空**：{bear.get('label')}")
        elif scenario_type == "upper_shadow":
            high = sc.get("session_high")
            close_px = sc.get("session_close")
            low = sc.get("session_low")
            bear = sc.get("bearish") or {}
            bull = sc.get("bullish") or {}
            lines.append(f"- **{name} {code}** · 长上影 setup（{setup_date}）")
            lines.append(f"  - 高 **{high}** / 收 **{close_px}** / 低 **{low}**")
            lines.append(
                f"  - 📉 **见顶**：{bear.get('label') or '低开低走跌破 setup 低点'}"
                f"（<{low}）"
            )
            lines.append(
                f"  - 📈 **洗盘**：{bull.get('label') or '高开反包 setup 高点'}"
                f"（>{high}）"
            )

        if eval_from:
            lines.append(f"  - 验证自 **{eval_from}** 起")
        if note:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def run_close_technical_watch(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    symbols: Optional[list[str]] = None,
    path: Optional[Path] = None,
    register: bool = True,
    render: bool = True,
) -> dict[str, Any]:
    """Register upper-shadow setups at close and build Feishu markdown."""
    cfg = technical_watch_cfg(settings)
    if not cfg.get("enabled", True):
        return {"markdown": "", "registered": [], "scenarios": []}

    from agent_reach.daily_run.symbols import (
        build_enriched_symbols,
        list_target_symbols,
        portfolio_from_snapshot,
    )

    day = today_shanghai().isoformat()
    pf = portfolio_from_snapshot(snapshot)
    target_codes = symbols or list_target_symbols(pf, mode="all")
    if not target_codes:
        primary = snapshot.get("code")
        if primary:
            target_codes = [_normalize_code(str(primary))]

    enriched = build_enriched_symbols(snapshot, settings)
    if register and target_codes:
        from agent_reach.daily_run.intraday import load_state
        from agent_reach.daily_run.quote_fetch import fetch_quotes_map

        quote_result = fetch_quotes_map(target_codes, settings=settings)
        for code in target_codes:
            row = enriched.setdefault(code, {})
            quote = (quote_result.quotes or {}).get(code) or {}
            for key in (
                "price",
                "change_pct",
                "name",
                "day_high",
                "day_low",
                "reference_price",
                "volume_ratio",
                "turnover",
                "turnover_rate",
            ):
                if quote.get(key) is not None:
                    row[key] = quote[key]

    registered: list[dict[str, Any]] = []
    if register:
        from agent_reach.daily_run.intraday import load_state

        for code in target_codes:
            row = enriched.get(code) or {}
            name = str(row.get("name") or code)
            sym_snapshot = {"code": code, **row}
            state = load_state(code=code)
            session_scans = list(state.scans or [])
            scenario = maybe_register_upper_shadow_from_session(
                code=code,
                name=name,
                snapshot=sym_snapshot,
                session_scans=session_scans,
                settings=settings,
                setup_date=day,
                path=path,
            )
            if scenario:
                registered.append(scenario)
            shrink = maybe_register_limit_up_shrink_pullback_from_session(
                code=code,
                name=name,
                snapshot=sym_snapshot,
                session_scans=session_scans,
                settings=settings,
                setup_date=day,
                path=path,
            )
            if shrink:
                registered.append(shrink)
            liquidity = maybe_register_liquidity_shrink_from_session(
                code=code,
                name=name,
                snapshot=sym_snapshot,
                session_scans=session_scans,
                settings=settings,
                setup_date=day,
                path=path,
            )
            if liquidity:
                registered.append(liquidity)

        holdings_codes = list_target_symbols(pf, mode="holdings") or target_codes
        mss_row = maybe_register_mss_trend_from_session(
            symbols=holdings_codes,
            settings=settings,
            setup_date=day,
            path=path,
        )
        if mss_row:
            registered.append(mss_row)
        cash_cap_row = maybe_register_min_cash_ratio_cap_from_session(
            enriched,
            settings=settings,
            setup_date=day,
            path=path,
        )
        if cash_cap_row:
            registered.append(cash_cap_row)

    scenarios = scenarios_for_setup_date(day, path=path)
    markdown = format_close_technical_watch_markdown(scenarios, settings=settings) if render else ""
    return {"markdown": markdown, "registered": registered, "scenarios": scenarios}
