# -*- coding: utf-8
"""Harness-evolved MarketEmotion scoring thresholds (a-stock-review)."""

from __future__ import annotations

import re
from typing import Any, Optional

_EMOTION_PREFIX = "market_emotion最优"
_EMOTION_RE = re.compile(
    r"market_emotion最优："
    r"ratio_strong=([\d.]+)\s+"
    r"ratio_neutral=([\d.]+)\s+"
    r"limit_up_hot=([\d.]+)\s+"
    r"score_strong_min=([\d.]+)\s+"
    r"score_neutral_min=([\d.]+)",
    re.IGNORECASE,
)

_EMOTION_KEYS: tuple[str, ...] = (
    "ratio_strong",
    "ratio_neutral",
    "limit_up_hot",
    "limit_up_normal",
    "limit_down_panic",
    "limit_down_local",
    "broken_rate_weak",
    "broken_rate_moderate",
    "north_inflow_strong",
    "north_outflow_strong",
    "score_strong_min",
    "score_neutral_min",
    "index_pct_bull",
    "index_pct_bear",
)

_EMOTION_BOUNDS: dict[str, tuple[float, float]] = {
    "ratio_strong": (1.5, 3.0),
    "ratio_neutral": (0.8, 1.5),
    "limit_up_hot": (60.0, 120.0),
    "limit_up_normal": (25.0, 60.0),
    "limit_down_panic": (30.0, 80.0),
    "limit_down_local": (10.0, 40.0),
    "broken_rate_weak": (0.2, 0.45),
    "broken_rate_moderate": (0.1, 0.35),
    "north_inflow_strong": (30.0, 100.0),
    "north_outflow_strong": (30.0, 100.0),
    "score_strong_min": (3.0, 6.0),
    "score_neutral_min": (0.0, 3.0),
    "index_pct_bull": (0.5, 2.0),
    "index_pct_bear": (-2.0, -0.5),
}

_EMOTION_NEUTRAL: dict[str, float] = {
    "ratio_strong": 2.0,
    "ratio_neutral": 1.0,
    "limit_up_hot": 80.0,
    "limit_up_normal": 40.0,
    "limit_down_panic": 50.0,
    "limit_down_local": 20.0,
    "broken_rate_weak": 0.3,
    "broken_rate_moderate": 0.2,
    "north_inflow_strong": 50.0,
    "north_outflow_strong": 50.0,
    "score_strong_min": 4.0,
    "score_neutral_min": 1.0,
    "index_pct_bull": 1.0,
    "index_pct_bear": -1.0,
}


def _market_review_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("market_review") or {})


def _emotion_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _market_review_section(settings)
    mode = str(sec.get("emotion_mode") or sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def market_emotion_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _market_review_section(settings)
    merged = dict(_EMOTION_NEUTRAL)
    for key in _EMOTION_KEYS:
        if key in sec:
            merged[key] = float(sec[key])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _EMOTION_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _EMOTION_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 4)
    for key in _EMOTION_KEYS:
        if key not in out:
            out[key] = float(_EMOTION_NEUTRAL[key])
    if out.get("ratio_neutral", 1.0) >= out.get("ratio_strong", 2.0):
        out["ratio_neutral"] = max(_EMOTION_BOUNDS["ratio_neutral"][0], out["ratio_strong"] - 0.5)
    if out.get("limit_up_normal", 40.0) >= out.get("limit_up_hot", 80.0):
        out["limit_up_normal"] = max(_EMOTION_BOUNDS["limit_up_normal"][0], out["limit_up_hot"] - 10.0)
    if out.get("score_neutral_min", 1.0) >= out.get("score_strong_min", 4.0):
        out["score_neutral_min"] = max(0.0, out["score_strong_min"] - 1.0)
    return out


def format_market_emotion_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = [
        f"ratio_strong={float(ratios.get('ratio_strong', 2.0)):g}",
        f"ratio_neutral={float(ratios.get('ratio_neutral', 1.0)):g}",
        f"limit_up_hot={float(ratios.get('limit_up_hot', 80.0)):g}",
        f"score_strong_min={float(ratios.get('score_strong_min', 4.0)):g}",
        f"score_neutral_min={float(ratios.get('score_neutral_min', 1.0)):g}",
    ]
    line = f"{_EMOTION_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_market_emotion_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _EMOTION_RE.search(str(text or ""))
    if not match:
        return None
    keys = (
        "ratio_strong",
        "ratio_neutral",
        "limit_up_hot",
        "score_strong_min",
        "score_neutral_min",
    )
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(keys)}
    merged = dict(_EMOTION_NEUTRAL)
    merged.update(raw)
    return _clamp_policy(merged)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_market_emotion_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_market_emotion_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase, resolve_harness_trade_signals

    if _overlay_has_phrase(state, "市场宽度不足", settings=settings) or _overlay_has_phrase(
        state, "暂无仓位建议", settings=settings
    ):
        merged["score_neutral_min"] = min(
            float(merged.get("score_neutral_min", 1.0)) + 1.0,
            _EMOTION_BOUNDS["score_neutral_min"][1],
        )
        merged["ratio_neutral"] = min(
            float(merged.get("ratio_neutral", 1.0)) + 0.1,
            _EMOTION_BOUNDS["ratio_neutral"][1],
        )
    if _overlay_has_phrase(state, "降级", settings=settings) and _overlay_has_phrase(
        state, "情绪", settings=settings
    ):
        merged["score_strong_min"] = min(
            float(merged.get("score_strong_min", 4.0)) + 1.0,
            _EMOTION_BOUNDS["score_strong_min"][1],
        )
    signals = resolve_harness_trade_signals(state, settings=settings)
    if signals.get("defensive_trim") or signals.get("pnl_target_miss"):
        merged["score_neutral_min"] = min(
            float(merged.get("score_neutral_min", 1.0)) + 1.0,
            _EMOTION_BOUNDS["score_neutral_min"][1],
        )
        merged["limit_up_hot"] = min(
            float(merged.get("limit_up_hot", 80.0)) + 5.0,
            _EMOTION_BOUNDS["limit_up_hot"][1],
        )
    elif signals.get("pnl_target_hit"):
        merged["score_neutral_min"] = max(
            float(merged.get("score_neutral_min", 1.0)) - 0.5,
            _EMOTION_BOUNDS["score_neutral_min"][0],
        )
    return merged


def apply_market_emotion_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _emotion_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_market_emotion_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = market_emotion_policy_base(settings)
    if _emotion_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_market_emotion_signal_evolution(merged, state, settings=settings)
    apply_market_emotion_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _market_emotion_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _emotion_mode(cfg) == "fixed":
        return _clamp_policy(market_emotion_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("market_emotion_policy")
    if isinstance(cached, dict) and cached:
        merged = market_emotion_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _EMOTION_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(market_emotion_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_market_emotion_policy(load_harness(), settings=cfg)


def market_emotion_policy_default(settings: Optional[dict[str, Any]], key: str) -> float:
    if settings is None:
        return float(_EMOTION_NEUTRAL.get(key, 0.0))
    return float(_market_emotion_policy(settings).get(key, _EMOTION_NEUTRAL.get(key, 0.0)))


def rating_position_from_score(
    score: int,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    strong_min = int(round(market_emotion_policy_default(settings, "score_strong_min")))
    neutral_min = int(round(market_emotion_policy_default(settings, "score_neutral_min")))
    if score >= strong_min:
        return "强", "7-8成"
    if score >= neutral_min:
        return "中", "5成"
    return "弱", "2-3成"


def market_emotion_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _market_review_section(settings)
    policy = _market_emotion_policy(settings)
    out = dict(sec)
    out.update(
        {
            "emotion_mode": _emotion_mode(settings),
            "harness_evolve": sec.get("harness_evolve", True),
            **{key: float(policy[key]) for key in _EMOTION_KEYS},
        }
    )
    return out


def harness_market_emotion_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _EMOTION_KEYS:
        base_val = float(base_policy.get(key, _EMOTION_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
