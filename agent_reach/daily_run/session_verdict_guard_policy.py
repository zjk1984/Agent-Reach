# -*- coding: utf-8
"""Harness-evolved session verdict guards + watchlist drawdown thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_SESSION_PREFIX = "session_verdict最优"
_SESSION_RE = re.compile(
    r"session_verdict最优："
    r"price_pullback_pct=([\d.]+)\s+"
    r"mss_pullback_pts=([\d.]+)",
    re.IGNORECASE,
)

_DRAWDOWN_PREFIX = "watchlist_drawdown最优"
_DRAWDOWN_RE = re.compile(
    r"watchlist_drawdown最优："
    r"yellow_pct=(-?[\d.]+)\s+"
    r"red_pct=(-?[\d.]+)",
    re.IGNORECASE,
)

_SESSION_KEYS: tuple[str, ...] = ("price_pullback_pct", "mss_pullback_pts")
_DRAWDOWN_KEYS: tuple[str, ...] = ("yellow_pct", "red_pct")

_SESSION_NEUTRAL: dict[str, float] = {
    "price_pullback_pct": 2.0,
    "mss_pullback_pts": 2.0,
}

_DRAWDOWN_NEUTRAL: dict[str, float] = {
    "yellow_pct": -3.0,
    "red_pct": -5.0,
}

_SESSION_BOUNDS: dict[str, tuple[float, float]] = {
    "price_pullback_pct": (1.0, 4.0),
    "mss_pullback_pts": (1.0, 5.0),
}

_DRAWDOWN_BOUNDS: dict[str, tuple[float, float]] = {
    "yellow_pct": (-5.0, -1.5),
    "red_pct": (-8.0, -3.0),
}


def _intraday_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("intraday") or {})


def _session_block(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict(_intraday_section(settings).get("session_verdict_guards") or {})


def _drawdown_block(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict(_intraday_section(settings).get("watchlist_drawdown") or {})


def session_verdict_mode(settings: Optional[dict[str, Any]]) -> str:
    block = _session_block(settings)
    mode = str(block.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def watchlist_drawdown_mode(settings: Optional[dict[str, Any]]) -> str:
    block = _drawdown_block(settings)
    mode = str(block.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def session_verdict_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    block = _session_block(settings)
    merged = dict(_SESSION_NEUTRAL)
    for key in _SESSION_KEYS:
        if key in block:
            merged[key] = float(block[key])
    return merged


def watchlist_drawdown_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    block = _drawdown_block(settings)
    merged = dict(_DRAWDOWN_NEUTRAL)
    for key in _DRAWDOWN_KEYS:
        if key in block:
            merged[key] = float(block[key])
    return merged


def _clamp_session_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _SESSION_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _SESSION_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 2)
    for key in _SESSION_KEYS:
        if key not in out:
            out[key] = float(_SESSION_NEUTRAL[key])
    return out


def _clamp_drawdown_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _DRAWDOWN_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _DRAWDOWN_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 2)
    if "yellow_pct" in out and "red_pct" in out and out["yellow_pct"] <= out["red_pct"]:
        out["red_pct"] = min(_DRAWDOWN_BOUNDS["red_pct"][1], out["yellow_pct"] - 0.5)
    for key in _DRAWDOWN_KEYS:
        if key not in out:
            out[key] = float(_DRAWDOWN_NEUTRAL[key])
    return out


def format_session_verdict_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    line = (
        f"{_SESSION_PREFIX}："
        f"price_pullback_pct={float(ratios.get('price_pullback_pct', 2.0)):.2f} "
        f"mss_pullback_pts={float(ratios.get('mss_pullback_pts', 2.0)):.2f}"
    )
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def format_watchlist_drawdown_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    line = (
        f"{_DRAWDOWN_PREFIX}："
        f"yellow_pct={float(ratios.get('yellow_pct', -3.0)):.2f} "
        f"red_pct={float(ratios.get('red_pct', -5.0)):.2f}"
    )
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_session_verdict_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _SESSION_RE.search(str(text or ""))
    if not match:
        return None
    return _clamp_session_policy(
        {
            "price_pullback_pct": float(match.group(1)),
            "mss_pullback_pts": float(match.group(2)),
        }
    )


def parse_watchlist_drawdown_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _DRAWDOWN_RE.search(str(text or ""))
    if not match:
        return None
    return _clamp_drawdown_policy(
        {
            "yellow_pct": float(match.group(1)),
            "red_pct": float(match.group(2)),
        }
    )


def _find_session_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_session_verdict_policy_line(blob)
        if parsed:
            return parsed
    return None


def _find_drawdown_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_watchlist_drawdown_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_session_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import (
        _overlay_has_phrase,
        evolution_mode,
        resolve_harness_trade_signals,
    )

    signals = resolve_harness_trade_signals(state, settings=settings)

    def _tighten(price_ceiling: float, mss_ceiling: float) -> None:
        if evolution_mode(settings, "price_pullback_pct") == "harness":
            merged["price_pullback_pct"] = min(
                float(merged.get("price_pullback_pct", 2.0)),
                price_ceiling,
            )
        if evolution_mode(settings, "mss_pullback_pts") == "harness":
            merged["mss_pullback_pts"] = min(
                float(merged.get("mss_pullback_pts", 2.0)),
                mss_ceiling,
            )

    def _loosen(price_floor: float, mss_floor: float) -> None:
        if evolution_mode(settings, "price_pullback_pct") == "harness":
            merged["price_pullback_pct"] = max(
                float(merged.get("price_pullback_pct", 2.0)),
                price_floor,
            )
        if evolution_mode(settings, "mss_pullback_pts") == "harness":
            merged["mss_pullback_pts"] = max(
                float(merged.get("mss_pullback_pts", 2.0)),
                mss_floor,
            )

    if signals.get("defensive_trim") or signals.get("deviation_active") or signals.get("pnl_target_miss"):
        _tighten(1.8, 1.8)
    if _overlay_has_phrase(state, "冲高回落降级", settings=settings) or _overlay_has_phrase(
        state, "冲高回落", settings=settings
    ):
        _tighten(1.9, 1.9)
    if _overlay_has_phrase(state, "误降级", settings=settings) or _overlay_has_phrase(
        state, "过早观察", settings=settings
    ):
        _loosen(2.5, 2.5)
    if _overlay_has_phrase(state, "观望正确", settings=settings):
        _tighten(2.0, 2.0)
    return merged


def _apply_drawdown_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase, evolution_mode

    def _tighten(yellow_floor: float, red_floor: float) -> None:
        if evolution_mode(settings, "yellow_pct") == "harness":
            merged["yellow_pct"] = max(float(merged.get("yellow_pct", -3.0)), yellow_floor)
        if evolution_mode(settings, "red_pct") == "harness":
            merged["red_pct"] = max(float(merged.get("red_pct", -5.0)), red_floor)

    def _loosen(yellow_ceiling: float, red_ceiling: float) -> None:
        if evolution_mode(settings, "yellow_pct") == "harness":
            merged["yellow_pct"] = min(float(merged.get("yellow_pct", -3.0)), yellow_ceiling)
        if evolution_mode(settings, "red_pct") == "harness":
            merged["red_pct"] = min(float(merged.get("red_pct", -5.0)), red_ceiling)

    if _overlay_has_phrase(state, "跌幅无预警", settings=settings) or _overlay_has_phrase(
        state, "观察池跌幅哨兵", settings=settings
    ) and _overlay_has_phrase(state, "暴跌", settings=settings):
        _tighten(-2.5, -4.0)
    if _overlay_has_phrase(state, "观察池预警", settings=settings) and _overlay_has_phrase(
        state, "误报", settings=settings
    ):
        _loosen(-3.5, -5.5)
    if _overlay_has_phrase(state, "海康", settings=settings) or _overlay_has_phrase(
        state, "工业富联", settings=settings
    ):
        _tighten(-2.8, -4.5)
    return merged


def apply_session_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if session_verdict_mode(settings) != "harness":
        return False
    optimal = _find_session_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    from agent_reach.daily_run.harness_policy import evolution_mode

    for key in _SESSION_KEYS:
        if evolution_mode(settings, key) == "harness" and key in optimal:
            merged[key] = optimal[key]
    return True


def apply_drawdown_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if watchlist_drawdown_mode(settings) != "harness":
        return False
    optimal = _find_drawdown_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    from agent_reach.daily_run.harness_policy import evolution_mode

    for key in _DRAWDOWN_KEYS:
        if evolution_mode(settings, key) == "harness" and key in optimal:
            merged[key] = optimal[key]
    return True


def resolve_harness_session_verdict_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = session_verdict_policy_base(settings)
    if session_verdict_mode(settings) != "harness":
        return _clamp_session_policy(merged)
    from agent_reach.daily_run.harness_policy import (
        _overlay_enabled,
        _restore_fixed_evolution_keys,
    )

    if not _overlay_enabled(settings):
        return _clamp_session_policy(merged)
    base = dict(merged)
    merged = _apply_session_signal_evolution(merged, state, settings=settings)
    apply_session_llm_optimal_to_policy(merged, state, settings=settings)
    merged = _restore_fixed_evolution_keys(merged, base, settings, _SESSION_KEYS)
    return _clamp_session_policy(merged)


def resolve_harness_watchlist_drawdown_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = watchlist_drawdown_policy_base(settings)
    if watchlist_drawdown_mode(settings) != "harness":
        return _clamp_drawdown_policy(merged)
    from agent_reach.daily_run.harness_policy import (
        _overlay_enabled,
        _restore_fixed_evolution_keys,
    )

    if not _overlay_enabled(settings):
        return _clamp_drawdown_policy(merged)
    base = dict(merged)
    merged = _apply_drawdown_signal_evolution(merged, state, settings=settings)
    apply_drawdown_llm_optimal_to_policy(merged, state, settings=settings)
    merged = _restore_fixed_evolution_keys(merged, base, settings, _DRAWDOWN_KEYS)
    return _clamp_drawdown_policy(merged)


def _session_verdict_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if session_verdict_mode(cfg) == "fixed":
        return _clamp_session_policy(session_verdict_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("session_verdict_policy")
    if isinstance(cached, dict) and cached:
        merged = session_verdict_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _SESSION_KEYS})
        return _clamp_session_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_session_policy(session_verdict_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_session_verdict_policy(load_harness(), settings=cfg)


def _watchlist_drawdown_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if watchlist_drawdown_mode(cfg) == "fixed":
        return _clamp_drawdown_policy(watchlist_drawdown_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("watchlist_drawdown_policy")
    if isinstance(cached, dict) and cached:
        merged = watchlist_drawdown_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _DRAWDOWN_KEYS})
        return _clamp_drawdown_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_drawdown_policy(watchlist_drawdown_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_watchlist_drawdown_policy(load_harness(), settings=cfg)


def session_verdict_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_session_verdict_policy(settings).get(key, _SESSION_NEUTRAL.get(key, 0.0)))


def watchlist_drawdown_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_watchlist_drawdown_policy(settings).get(key, _DRAWDOWN_NEUTRAL.get(key, 0.0)))


def session_verdict_guard_effective_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = _session_block(settings)
    policy = _session_verdict_policy(settings)
    return {
        **block,
        "mode": session_verdict_mode(settings),
        "enabled": block.get("enabled", True) is not False,
        "min_scan_num": max(2, int(block.get("min_scan_num", 4))),
        "price_pullback_pct": float(policy["price_pullback_pct"]),
        "mss_pullback_pts": float(policy["mss_pullback_pts"]),
    }


def watchlist_drawdown_effective_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = _drawdown_block(settings)
    policy = _watchlist_drawdown_policy(settings)
    return {
        **block,
        "mode": watchlist_drawdown_mode(settings),
        "enabled": block.get("enabled", True) is not False,
        "yellow_pct": float(policy["yellow_pct"]),
        "red_pct": float(policy["red_pct"]),
    }


def harness_session_verdict_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _SESSION_KEYS:
        base_val = float(base_policy.get(key, _SESSION_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed


def harness_watchlist_drawdown_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _DRAWDOWN_KEYS:
        base_val = float(base_policy.get(key, _DRAWDOWN_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed


def session_verdict_harness_evidence(
    *,
    report: Optional[dict[str, Any]] = None,
    alerts: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, list[str]]:
    """Build harness memory/policy lines from pullback downgrade + drawdown alerts."""
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []

    meta = (report or {}).get("session_pullback_downgrade")
    if meta:
        name = str((report or {}).get("name") or (report or {}).get("code") or "标的")
        memory.append(
            f"冲高回落降级 {name}：{meta.get('morning_scan')} {meta.get('morning_verdict')}→观察"
        )
        policy.append(
            format_session_verdict_policy_line(
                _session_verdict_policy(settings),
                rationale="盘中 S4+ 冲高回落降级",
            )
        )
        playbook.append(f"session_verdict：{name} 早盘可做后降级观察，收紧 price_pullback / mss_pullback")

    for alert in alerts or []:
        if not isinstance(alert, dict):
            continue
        text = str(alert.get("text") or alert.get("name") or "")
        severity = str(alert.get("severity") or "")
        if not text:
            continue
        memory.append(f"观察池跌幅哨兵 {severity}：{text}")
        if severity == "red":
            policy.append(
                format_watchlist_drawdown_policy_line(
                    _watchlist_drawdown_policy(settings),
                    rationale="观察池深跌预警",
                )
            )
            playbook.append("watchlist_drawdown：深跌触红线，下日收紧 yellow/red 阈值")

    return {"memory": memory, "policy": policy, "playbook": playbook, "plan": []}
