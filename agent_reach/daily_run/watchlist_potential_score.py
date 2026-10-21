# -*- coding: utf-8
"""Ambush watchlist potential score — mainline + MSS room + low position − hot-chase penalties."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_POTENTIAL_NEUTRAL: dict[str, Any] = {
    "enabled": True,
    "weight_mainline": 25.0,
    "weight_mss_room": 20.0,
    "weight_position": 20.0,
    "weight_quality": 15.0,
    "penalty_hot_chase": 20.0,
    "penalty_limit_up_chase": 15.0,
    "mss_room_anchor": 55.0,
    "mss_room_span": 30.0,
    "hot_chase_change_pct": 6.0,
    "hot_chase_cumulative_3d_pct": 10.0,
    "hot_chase_volume_ratio": 2.2,
    "limit_up_change_pct": 9.5,
    "limit_up_boards_min": 1,
    "limit_up_distance_pct": 4.0,
}

_REASON_LABELS: dict[str, str] = {
    "mainline": "主线共振",
    "mss_room": "MSS上行空间",
    "position": "20日偏低",
    "quality": "质量门",
    "hot_chase": "热点追高",
    "limit_up": "涨停追高",
}


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def watchlist_potential_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    wl = dict((settings or {}).get("watchlist") or {})
    block = dict(wl.get("potential_score") or {})
    out = {**_POTENTIAL_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", True)) is not False
    return out


def watchlist_potential_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return bool(watchlist_potential_cfg(settings).get("enabled", True))


@dataclass
class WatchlistPotentialResult:
    score: float
    primary_reason: str
    components: dict[str, float] = field(default_factory=dict)

    def one_liner(self) -> str:
        return f"潜力 {int(round(self.score))} · {self.primary_reason}"


def _symbol_mss(row: dict[str, Any], *, base_mss: float) -> float:
    mss = _optional_float(row.get("mss_final") or row.get("mss_score"))
    if mss is not None:
        return mss
    return float(base_mss)


def _mainline_component(
    code: str,
    row: dict[str, Any],
    *,
    settings: dict[str, Any],
    weight: float,
) -> tuple[float, str]:
    score = 0.0
    try:
        from agent_reach.daily_run.tsp.intraday_sentinel import match_symbol_tsp_mainline

        sym_data = {
            "sector": row.get("sector") or row.get("industry"),
            "industry": row.get("industry") or row.get("sector"),
        }
        match = match_symbol_tsp_mainline(code, sym_data, settings=settings)
        if match.is_mainline:
            score = weight
        elif (match.score or 0) >= 15:
            score = weight * 0.45
        elif _optional_float(row.get("mainline_score") or 0) >= 20:
            score = weight * 0.35
    except Exception:
        ml = _optional_float(row.get("mainline_score"))
        if ml is not None and ml >= 20:
            score = weight * min(1.0, ml / 100.0)
    if score >= weight * 0.9:
        return score, "mainline"
    if score > 0:
        return score, "mainline"
    return 0.0, ""


def _mss_room_component(
    row: dict[str, Any],
    *,
    base_mss: float,
    cfg: dict[str, Any],
) -> tuple[float, str]:
    weight = float(cfg["weight_mss_room"])
    mss = _symbol_mss(row, base_mss=base_mss)
    anchor = float(cfg["mss_room_anchor"])
    span = max(float(cfg["mss_room_span"]), 1.0)
    room = max(0.0, min(1.0, (anchor - mss) / span))
    if room < 0.05:
        return 0.0, ""
    return weight * room, "mss_room"


def _position_component(row: dict[str, Any], *, cfg: dict[str, Any]) -> tuple[float, str]:
    weight = float(cfg["weight_position"])
    pos = _optional_float(row.get("position_20d"))
    if pos is None:
        return weight * 0.35, "position"
    low = max(0.0, min(1.0, 1.0 - pos))
    if low < 0.2:
        return 0.0, ""
    return weight * low, "position"


def _quality_component(
    code: str,
    row: dict[str, Any],
    *,
    snapshot: Optional[dict[str, Any]],
    settings: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[float, str]:
    weight = float(cfg["weight_quality"])
    snap = {
        "code": code,
        "name": row.get("name"),
        "mss_final": row.get("mss_final"),
        "mss_breakdown": row.get("mss_breakdown") or (snapshot or {}).get("mss_breakdown"),
        "price": row.get("price"),
        "sector": row.get("sector"),
        **{k: row[k] for k in ("roe", "gross_margin", "gross_margin_pct") if k in row},
    }
    from agent_reach.daily_run.berkshire.quality_screen import screen_from_snapshot

    qs = screen_from_snapshot(snap, enriched=row)
    if qs.passed:
        return weight, "quality"
    if "数据不足" in qs.reason:
        return weight * 0.5, "quality"
    return 0.0, ""


def _hot_on_list(keywords: list[str], hot_titles: list[str]) -> bool:
    if not hot_titles or not keywords:
        return False
    from agent_reach.daily_run.hot_news_collector import _matches_keywords

    return any(_matches_keywords(title, keywords) for title in hot_titles)


def _hot_chase_penalty(
    row: dict[str, Any],
    *,
    cand: dict[str, Any],
    hot_titles: list[str],
    cfg: dict[str, Any],
) -> tuple[float, str]:
    penalty = float(cfg["penalty_hot_chase"])
    keywords = list(cand.get("keywords") or [])
    name = str(cand.get("name") or row.get("name") or "")
    if name:
        keywords.extend([name, name[:4]])
    on_hot = _hot_on_list(keywords, hot_titles)
    chg = _optional_float(row.get("change_pct"))
    cum3 = _optional_float(row.get("cumulative_3d_pct"))
    vol_ratio = _optional_float(row.get("volume_ratio"))
    chased = False
    if on_hot and chg is not None and chg >= float(cfg["hot_chase_change_pct"]):
        chased = True
    if on_hot and cum3 is not None and cum3 >= float(cfg["hot_chase_cumulative_3d_pct"]):
        chased = True
    if on_hot and vol_ratio is not None and vol_ratio >= float(cfg["hot_chase_volume_ratio"]):
        chased = True
    if not chased:
        return 0.0, ""
    return penalty, "hot_chase"


def _limit_up_penalty(row: dict[str, Any], *, cfg: dict[str, Any]) -> tuple[float, str]:
    penalty = float(cfg["penalty_limit_up_chase"])
    chg = _optional_float(row.get("change_pct"))
    boards = int(row.get("consecutive_boards") or row.get("consecutive_limit_ups") or 0)
    dist = _optional_float(row.get("distance_to_limit_pct"))
    hit = False
    if boards >= int(cfg["limit_up_boards_min"]):
        hit = True
    if chg is not None and chg >= float(cfg["limit_up_change_pct"]):
        hit = True
    if dist is not None and dist <= float(cfg["limit_up_distance_pct"]):
        hit = True
    if not hit:
        return 0.0, ""
    return penalty, "limit_up"


def _pick_primary(components: dict[str, float]) -> str:
    positives = {k: v for k, v in components.items() if v > 0 and not k.startswith("_")}
    penalties = {k: v for k, v in components.items() if v < 0}
    if penalties:
        worst = min(penalties, key=lambda k: penalties[k])
        return _REASON_LABELS.get(worst, worst)
    if not positives:
        return "综合"
    best = max(positives, key=lambda k: positives[k])
    return _REASON_LABELS.get(best, best)


def compute_watchlist_potential(
    cand: dict[str, Any],
    *,
    row: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    base_mss: float = 50.0,
    hot_titles: Optional[list[str]] = None,
) -> WatchlistPotentialResult:
    cfg = watchlist_potential_cfg(settings)
    merged = {**(row or {}), **{k: v for k, v in cand.items() if v is not None}}
    code = _normalize_code(str(merged.get("code") or ""))
    titles = list(hot_titles or [])

    components: dict[str, float] = {}
    ml, ml_key = _mainline_component(
        code, merged, settings=settings or {}, weight=float(cfg["weight_mainline"])
    )
    if ml_key:
        components[ml_key] = ml
    mss, mss_key = _mss_room_component(merged, base_mss=base_mss, cfg=cfg)
    if mss_key:
        components[mss_key] = mss
    pos, pos_key = _position_component(merged, cfg=cfg)
    if pos_key:
        components[pos_key] = pos
    qual, qual_key = _quality_component(
        code, merged, snapshot=snapshot, settings=settings or {}, cfg=cfg
    )
    if qual_key:
        components[qual_key] = qual

    hot_pen, hot_key = _hot_chase_penalty(
        merged, cand=cand, hot_titles=titles, cfg=cfg
    )
    if hot_key:
        components[hot_key] = -hot_pen
    lim_pen, lim_key = _limit_up_penalty(merged, cfg=cfg)
    if lim_key:
        components[lim_key] = -lim_pen

    max_pos = (
        float(cfg["weight_mainline"])
        + float(cfg["weight_mss_room"])
        + float(cfg["weight_position"])
        + float(cfg["weight_quality"])
    )
    raw = sum(components.values())
    score = max(0.0, min(100.0, 100.0 * raw / max(max_pos, 1.0)))
    primary = _pick_primary(components)
    return WatchlistPotentialResult(score=score, primary_reason=primary, components=components)


def format_watchlist_potential_one_liner(result: WatchlistPotentialResult) -> str:
    return result.one_liner()


def candidate_potential_sort_key(
    cand: dict[str, Any],
    *,
    enriched: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    base_mss: float,
    hot_titles: Optional[list[str]] = None,
) -> float:
    code = _normalize_code(str(cand.get("code", "")))
    row = enriched.get(code) or {}
    return compute_watchlist_potential(
        cand,
        row=row,
        snapshot=snapshot,
        settings=settings,
        base_mss=base_mss,
        hot_titles=hot_titles,
    ).score


def render_watchlist_potential_markdown(
    portfolio: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    *,
    snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    base_mss: float = 50.0,
    limit: int = 8,
) -> str:
    """One line per watchlist name for Feishu intraday cards."""
    if not watchlist_potential_enabled(settings):
        return ""
    watchlist = list(portfolio.get("watchlist") or [])
    if not watchlist:
        return ""
    lines = ["**观察池潜力**", ""]
    scored: list[tuple[float, str]] = []
    for w in watchlist:
        if not isinstance(w, dict):
            continue
        code = _normalize_code(str(w.get("code") or ""))
        cand = {"code": code, "name": w.get("name"), "keywords": w.get("keywords") or []}
        row = {**w, **enriched.get(code, {})}
        if w.get("potential_score") is not None and w.get("potential_reason"):
            pot_score = float(w["potential_score"])
            line = f"潜力 {int(round(pot_score))} · {w['potential_reason']}"
        else:
            pot = compute_watchlist_potential(
                cand,
                row=row,
                snapshot=snapshot,
                settings=settings,
                base_mss=base_mss,
            )
            pot_score = pot.score
            line = pot.one_liner()
        name = str(w.get("name") or code)
        scored.append((pot_score, f"- **{name}** ({code}) — {line}"))
    if not scored:
        return ""
    scored.sort(key=lambda x: x[0], reverse=True)
    for _, row in scored[:limit]:
        lines.append(row)
    return "\n".join(lines).strip()


def render_watchlist_candidates_potential_markdown(
    candidates: list[dict[str, Any]],
    enriched: dict[str, dict[str, Any]],
    *,
    snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    base_mss: float = 50.0,
    limit: int = 7,
) -> str:
    if not watchlist_potential_enabled(settings) or not candidates:
        return ""
    rows: list[tuple[float, str]] = []
    for cand in candidates:
        code = _normalize_code(str(cand.get("code") or ""))
        if not code:
            continue
        pot = compute_watchlist_potential(
            cand,
            row=enriched.get(code) or {},
            snapshot=snapshot,
            settings=settings,
            base_mss=base_mss,
        )
        name = str(cand.get("name") or code)
        rows.append((pot.score, f"- **{name}** ({code}) — {pot.one_liner()}"))
    if not rows:
        return ""
    rows.sort(key=lambda x: x[0], reverse=True)
    lines = ["**观察池候选潜力（Top）**", ""]
    lines.extend(line for _, line in rows[:limit])
    return "\n".join(lines).strip()
