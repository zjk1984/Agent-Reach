# -*- coding: utf-8
"""Harness-evolved watchlist intel score boost/penalty thresholds."""

from __future__ import annotations

import re
from typing import Any, Optional

_WATCHLIST_PREFIX = "watchlist_score最优"
_WATCHLIST_RE = re.compile(
    r"watchlist_score最优："
    r"announcement_score_boost=([\d.]+)\s+"
    r"news_score_boost=([\d.]+)\s+"
    r"negative_announcement_penalty=(-?[\d.]+)\s+"
    r"negative_news_penalty=(-?[\d.]+)\s+"
    r"hot_topic_remove_change_pct=(-?[\d.]+)",
    re.IGNORECASE,
)

_WATCHLIST_KEYS: tuple[str, ...] = (
    "announcement_score_boost",
    "news_score_boost",
    "negative_announcement_penalty",
    "negative_news_penalty",
    "hot_topic_remove_change_pct",
)

_WATCHLIST_BOUNDS: dict[str, tuple[float, float]] = {
    "announcement_score_boost": (0.0, 8.0),
    "news_score_boost": (0.0, 5.0),
    "negative_announcement_penalty": (-12.0, 0.0),
    "negative_news_penalty": (-8.0, 0.0),
    "hot_topic_remove_change_pct": (-8.0, 0.0),
}

_WATCHLIST_NEUTRAL: dict[str, float] = {
    "announcement_score_boost": 3.0,
    "news_score_boost": 1.0,
    "negative_announcement_penalty": -4.0,
    "negative_news_penalty": -2.0,
    "hot_topic_remove_change_pct": -2.0,
}


def _watchlist_section(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict((settings or {}).get("watchlist") or {})


def _watchlist_score_mode(settings: Optional[dict[str, Any]]) -> str:
    sec = _watchlist_section(settings)
    mode = str(sec.get("mode") or "harness").strip().lower()
    return mode if mode in {"harness", "fixed"} else "harness"


def watchlist_score_policy_base(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    sec = _watchlist_section(settings)
    merged = dict(_WATCHLIST_NEUTRAL)
    mapping = {
        "announcement_score_boost": "announcement_score_boost",
        "news_score_boost": "news_score_boost",
        "negative_announcement_penalty": "negative_announcement_penalty",
        "negative_news_penalty": "negative_news_penalty",
        "hot_topic_remove_change_pct": "hot_topic_remove_change_pct",
    }
    for key, src in mapping.items():
        if src in sec:
            merged[key] = float(sec[src])
    return merged


def _clamp_policy(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _WATCHLIST_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        lo, hi = _WATCHLIST_BOUNDS[key]
        out[key] = round(max(lo, min(hi, float(val))), 3)
    return out


def format_watchlist_score_policy_line(ratios: dict[str, float], *, rationale: str = "") -> str:
    parts = [f"{key}={float(ratios[key]):g}" for key in _WATCHLIST_KEYS if key in ratios]
    line = f"{_WATCHLIST_PREFIX}：" + " ".join(parts)
    reason = str(rationale or "").strip()
    if reason:
        line += f" — {reason[:120]}"
    return line


def parse_watchlist_score_policy_line(text: str) -> Optional[dict[str, float]]:
    match = _WATCHLIST_RE.search(str(text or ""))
    if not match:
        return None
    raw = {key: float(match.group(i + 1)) for i, key in enumerate(_WATCHLIST_KEYS)}
    return _clamp_policy(raw)


def _find_parsed_in_state(state: Any, *, settings: dict[str, Any]) -> Optional[dict[str, float]]:
    from agent_reach.daily_run.harness_policy import _collect_text_blobs, _overlay_sources

    for blob in _collect_text_blobs(
        state, sources=_overlay_sources(settings), kind="policy", settings=settings
    ):
        parsed = parse_watchlist_score_policy_line(blob)
        if parsed:
            return parsed
    return None


def _apply_watchlist_score_signal_evolution(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    from agent_reach.daily_run.harness_policy import _overlay_has_phrase

    if _overlay_has_phrase(state, "利空", settings=settings) or _overlay_has_phrase(
        state, "negative", settings=settings
    ):
        merged["negative_announcement_penalty"] = min(
            float(merged.get("negative_announcement_penalty", -4.0)) - 1.0,
            _WATCHLIST_BOUNDS["negative_announcement_penalty"][0],
        )
        merged["negative_news_penalty"] = min(
            float(merged.get("negative_news_penalty", -2.0)) - 0.5,
            _WATCHLIST_BOUNDS["negative_news_penalty"][0],
        )
        merged["hot_topic_remove_change_pct"] = min(
            float(merged.get("hot_topic_remove_change_pct", -2.0)) - 0.5,
            _WATCHLIST_BOUNDS["hot_topic_remove_change_pct"][0],
        )
    if _overlay_has_phrase(state, "watchlist", settings=settings) and _overlay_has_phrase(
        state, "boost", settings=settings
    ):
        merged["announcement_score_boost"] = min(
            float(merged.get("announcement_score_boost", 3.0)) + 0.5,
            _WATCHLIST_BOUNDS["announcement_score_boost"][1],
        )
    return merged


def apply_watchlist_score_llm_optimal_to_policy(
    merged: dict[str, float],
    state: Any,
    *,
    settings: dict[str, Any],
) -> bool:
    if _watchlist_score_mode(settings) != "harness":
        return False
    optimal = _find_parsed_in_state(state, settings=settings)
    if not optimal:
        return False
    merged.update(optimal)
    return True


def resolve_harness_watchlist_score_policy(
    state: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    merged = watchlist_score_policy_base(settings)
    if _watchlist_score_mode(settings) != "harness":
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(settings):
        return _clamp_policy(merged)
    merged = _apply_watchlist_score_signal_evolution(merged, state, settings=settings)
    apply_watchlist_score_llm_optimal_to_policy(merged, state, settings=settings)
    return _clamp_policy(merged)


def _watchlist_score_policy(settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    cfg = settings or {}
    if _watchlist_score_mode(cfg) == "fixed":
        return _clamp_policy(watchlist_score_policy_base(cfg))
    runtime = cfg.get("harness_runtime") or {}
    cached = runtime.get("watchlist_score_policy")
    if isinstance(cached, dict) and cached:
        merged = watchlist_score_policy_base(cfg)
        merged.update({k: float(v) for k, v in cached.items() if k in _WATCHLIST_KEYS})
        return _clamp_policy(merged)
    from agent_reach.daily_run.harness_policy import _overlay_enabled

    if not _overlay_enabled(cfg):
        return _clamp_policy(watchlist_score_policy_base(cfg))
    from agent_reach.daily_run.harness import load_harness

    return resolve_harness_watchlist_score_policy(load_harness(), settings=cfg)


def watchlist_score_policy_default(settings: dict[str, Any], key: str) -> float:
    return float(_watchlist_score_policy(settings).get(key, _WATCHLIST_NEUTRAL.get(key, 0.0)))


def watchlist_score_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sec = _watchlist_section(settings)
    policy = _watchlist_score_policy(settings)
    return {
        **sec,
        "mode": _watchlist_score_mode(settings),
        "harness_evolve": sec.get("harness_evolve", True),
        "announcement_score_boost": float(policy["announcement_score_boost"]),
        "news_score_boost": float(policy["news_score_boost"]),
        "negative_announcement_penalty": float(policy["negative_announcement_penalty"]),
        "negative_news_penalty": float(policy["negative_news_penalty"]),
        "hot_topic_remove_change_pct": float(policy["hot_topic_remove_change_pct"]),
    }


def harness_watchlist_score_overlay_meta(
    base_policy: dict[str, float],
    effective_policy: dict[str, float],
) -> dict[str, Any]:
    changed: dict[str, dict[str, float]] = {}
    for key in _WATCHLIST_KEYS:
        base_val = float(base_policy.get(key, _WATCHLIST_NEUTRAL.get(key, 0.0)))
        eff_val = float(effective_policy.get(key, base_val))
        if abs(eff_val - base_val) >= 0.01:
            changed[key] = {"base": base_val, "effective": eff_val}
    return changed
