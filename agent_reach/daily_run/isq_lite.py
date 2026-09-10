# -*- coding: utf-8
"""ISQ-lite — deterministic Investment Signal Quality metadata (DeepEar-inspired)."""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_WEIGHTS: dict[str, float] = {
    "sentiment": 0.15,
    "confidence": 0.2,
    "intensity": 0.15,
    "expectation_gap": 0.15,
    "timeliness": 0.15,
    "transmission": 0.2,
}


def isq_lite_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("isq_lite") or {})


def isq_lite_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return isq_lite_cfg(settings).get("enabled", True) is not False


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _composite(scores: dict[str, float], weights: dict[str, float]) -> float:
    total_w = 0.0
    total = 0.0
    for key, weight in weights.items():
        if key not in scores:
            continue
        total_w += weight
        total += float(scores[key]) * weight
    if total_w <= 0:
        return 0.0
    return round(total / total_w, 3)


def score_hot_topic_item(
    item: dict[str, Any],
    *,
    dual_source: bool = False,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Score a hot-topic row (60s / RedFox diff item)."""
    cfg = isq_lite_cfg(settings)
    weights = dict(cfg.get("dimension_weights") or _DEFAULT_WEIGHTS)
    title = str(item.get("title") or "")
    platform = str(item.get("platform") or "")
    sentiment = 0.55 if dual_source else 0.45
    confidence = 0.85 if dual_source else 0.55
    intensity = _clamp01(len(title) / 80.0)
    expectation_gap = 0.6 if not dual_source else 0.45
    timeliness = 0.9
    transmission = 0.7 if platform else 0.45
    scores = {
        "sentiment": round(sentiment, 3),
        "confidence": round(confidence, 3),
        "intensity": round(intensity, 3),
        "expectation_gap": round(expectation_gap, 3),
        "timeliness": round(timeliness, 3),
        "transmission": round(transmission, 3),
    }
    return {
        "isq": scores,
        "isq_composite": _composite(scores, weights),
    }


def score_hot_sector_row(
    row: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = isq_lite_cfg(settings)
    weights = dict(cfg.get("dimension_weights") or _DEFAULT_WEIGHTS)
    chg = float(row.get("change_pct") or 0.0)
    sector = str(row.get("sector") or row.get("name") or "")
    has_code = bool(row.get("code"))
    sentiment = _clamp01(0.5 + chg / 10.0)
    confidence = 0.75 if has_code else 0.5
    intensity = _clamp01(abs(chg) / 5.0)
    expectation_gap = 0.5
    timeliness = 0.85
    transmission = 0.8 if sector and sector != "未分类" else 0.4
    scores = {
        "sentiment": round(sentiment, 3),
        "confidence": round(confidence, 3),
        "intensity": round(intensity, 3),
        "expectation_gap": round(expectation_gap, 3),
        "timeliness": round(timeliness, 3),
        "transmission": round(transmission, 3),
    }
    return {
        "isq": scores,
        "isq_composite": _composite(scores, weights),
    }


def score_sector_research_row(
    row: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = isq_lite_cfg(settings)
    weights = dict(cfg.get("dimension_weights") or _DEFAULT_WEIGHTS)
    hits = list(row.get("hits") or [])
    success = row.get("success") is True
    summary_len = len(str(row.get("summary") or ""))
    sentiment = 0.55
    confidence = 0.8 if success and hits else 0.35
    intensity = _clamp01(summary_len / 400.0)
    expectation_gap = 0.55
    timeliness = 0.7
    transmission = 0.75 if row.get("label") else 0.5
    scores = {
        "sentiment": round(sentiment, 3),
        "confidence": round(confidence, 3),
        "intensity": round(intensity, 3),
        "expectation_gap": round(expectation_gap, 3),
        "timeliness": round(timeliness, 3),
        "transmission": round(transmission, 3),
    }
    return {
        "isq": scores,
        "isq_composite": _composite(scores, weights),
    }


def _annotate_items(items: list[dict[str, Any]], *, dual_source: bool, settings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        row.update(score_hot_topic_item(row, dual_source=dual_source, settings=settings))
        out.append(row)
    return out


def enrich_hot_topic_diff(diff: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not diff or not isq_lite_enabled(settings):
        return diff
    enriched = dict(diff)
    enriched["overlap"] = _annotate_items(list(diff.get("overlap") or []), dual_source=True, settings=settings)
    enriched["only_60s"] = _annotate_items(list(diff.get("only_60s") or []), dual_source=False, settings=settings)
    enriched["only_redfox"] = _annotate_items(list(diff.get("only_redfox") or []), dual_source=False, settings=settings)
    composites = [float(i.get("isq_composite") or 0) for i in enriched["overlap"]]
    if composites:
        enriched["isq_overlap_mean"] = round(sum(composites) / len(composites), 3)
    return enriched


def enrich_hot_sectors(
    rows: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    if not isq_lite_enabled(settings):
        return rows
    return [{**row, **score_hot_sector_row(row, settings=settings)} for row in rows]


def enrich_sector_research(
    rows: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    if not isq_lite_enabled(settings):
        return rows
    return [{**row, **score_sector_research_row(row, settings=settings)} for row in rows]


def enrich_weekly_isq(
    hot_sectors: list[dict[str, Any]],
    sector_research: list[dict[str, Any]],
    hot_topic_diff: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return (
        enrich_hot_sectors(hot_sectors, settings=settings),
        enrich_sector_research(sector_research, settings=settings),
        enrich_hot_topic_diff(hot_topic_diff, settings=settings),
    )


def render_isq_hot_sectors_markdown(rows: list[dict[str, Any]], *, limit: int = 5) -> str:
    scored = [r for r in rows if r.get("isq_composite") is not None]
    if not scored:
        return ""
    lines = ["### 📐 ISQ-lite · 强势标的", ""]
    for row in sorted(scored, key=lambda x: float(x.get("isq_composite") or 0), reverse=True)[:limit]:
        name = row.get("name") or row.get("code")
        chg = row.get("change_pct")
        chg_s = f"{float(chg):+.1f}%" if chg is not None else "—"
        tx = (row.get("isq") or {}).get("transmission")
        lines.append(
            f"- **{name}** {chg_s} · ISQ **{float(row.get('isq_composite')):.2f}**"
            + (f" · 传导 {float(tx):.2f}" if tx is not None else "")
        )
    lines.append("")
    return "\n".join(lines).strip()


def render_isq_hot_topic_markdown(diff: dict[str, Any], *, limit: int = 3) -> str:
    if not diff or diff.get("isq_overlap_mean") is None:
        return ""
    lines = [
        "### 📐 ISQ-lite · 双源热点",
        "",
        f"- 双源共识均分 **{float(diff['isq_overlap_mean']):.2f}** · "
        f"重叠 **{diff.get('overlap_count', 0)}** 条",
        "",
    ]
    for item in (diff.get("overlap") or [])[:limit]:
        comp = item.get("isq_composite")
        title = str(item.get("title") or "")[:48]
        lines.append(f"- [{item.get('platform', '?')}] {title} · ISQ **{float(comp):.2f}**")
    lines.append("")
    return "\n".join(lines).strip()
