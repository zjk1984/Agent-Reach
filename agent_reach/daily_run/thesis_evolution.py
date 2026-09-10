# -*- coding: utf-8
"""Cross-run thesis evolution diff (DeepEar --update-from style)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.job_checkpoint import JobCheckpoint, checkpoint_enabled


def thesis_evolution_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("thesis_evolution") or {})


def thesis_evolution_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return thesis_evolution_cfg(settings).get("enabled", True) is not False


def _themes_from_hot_sectors(rows: list[dict[str, Any]]) -> list[str]:
    themes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        theme = str(row.get("sector") or row.get("name") or "").strip()
        if not theme or theme in seen:
            continue
        seen.add(theme)
        themes.append(theme)
    return themes


def build_weekly_thesis_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    hot_sectors = list(report.get("hot_sectors") or [])
    narrative = dict(report.get("llm_narrative") or {})
    debate = dict(report.get("invest_debate_narrative") or {})
    diff = dict(report.get("hot_topic_diff") or {})
    return {
        "scope": "weekly",
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "themes": _themes_from_hot_sectors(hot_sectors),
        "hot_sector_codes": [str(r.get("code")) for r in hot_sectors if r.get("code")][:12],
        "narrative_summary": str(narrative.get("summary") or "")[:240],
        "invest_debate_summary": str(debate.get("summary") or "")[:240],
        "overlap_count": int(diff.get("overlap_count") or 0),
        "weekly_pnl_pct": report.get("weekly_pnl_pct"),
    }


def build_forecast_thesis_snapshot(forecast: dict[str, Any]) -> dict[str, Any]:
    narrative = dict(forecast.get("llm_narrative") or {})
    debate = dict(forecast.get("invest_debate_narrative") or {})
    symbols = forecast.get("symbols") or {}
    codes = list(symbols.keys())[:12]
    themes: list[str] = []
    for sym in symbols.values():
        if not isinstance(sym, dict):
            continue
        name = str(sym.get("name") or "").strip()
        if name and name not in themes:
            themes.append(name)
    return {
        "scope": "forecast",
        "week_start": forecast.get("week_start"),
        "week_end": forecast.get("week_end"),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "themes": themes[:8],
        "symbol_codes": codes,
        "narrative_summary": str(narrative.get("summary") or "")[:240],
        "invest_debate_summary": str(debate.get("summary") or "")[:240],
        "symbol_count": len(symbols),
    }


def compute_thesis_diff(current: dict[str, Any], prior: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not prior:
        return {
            "has_prior": False,
            "scope": current.get("scope"),
            "week_start": current.get("week_start"),
            "week_end": current.get("week_end"),
            "message": "无上一期快照，已建立 baseline",
        }
    cur_themes = set(current.get("themes") or [])
    prior_themes = set(prior.get("themes") or [])
    added = sorted(cur_themes - prior_themes)
    removed = sorted(prior_themes - cur_themes)
    kept = sorted(cur_themes & prior_themes)
    cur_summary = str(current.get("narrative_summary") or "").strip()
    prior_summary = str(prior.get("narrative_summary") or "").strip()
    narrative_changed = bool(cur_summary and prior_summary and cur_summary != prior_summary)
    overlap_delta = int(current.get("overlap_count") or 0) - int(prior.get("overlap_count") or 0)
    pnl_cur = current.get("weekly_pnl_pct")
    pnl_prior = prior.get("weekly_pnl_pct")
    pnl_delta = None
    if pnl_cur is not None and pnl_prior is not None:
        pnl_delta = round(float(pnl_cur) - float(pnl_prior), 3)
    drift_score = len(added) + len(removed) + (1 if narrative_changed else 0)
    return {
        "has_prior": True,
        "scope": current.get("scope"),
        "prior_week_start": prior.get("week_start"),
        "prior_week_end": prior.get("week_end"),
        "week_start": current.get("week_start"),
        "week_end": current.get("week_end"),
        "themes_added": added,
        "themes_removed": removed,
        "themes_kept": kept,
        "narrative_changed": narrative_changed,
        "prior_narrative_summary": prior_summary[:120],
        "current_narrative_summary": cur_summary[:120],
        "overlap_delta": overlap_delta,
        "weekly_pnl_pct_delta": pnl_delta,
        "drift_score": drift_score,
    }


def _list_scope_snapshots(scope: str, base_dir: Path) -> list[tuple[str, Path]]:
    prefix = f"thesis_{scope}_"
    hits: list[tuple[str, Path]] = []
    if not base_dir.exists():
        return hits
    for path in base_dir.glob(f"{prefix}*.json"):
        key = path.stem[len(prefix) :]
        hits.append((key, path))
    hits.sort(key=lambda x: x[0])
    return hits


def _load_prior_snapshot(scope: str, week_key: str, settings: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    ckpt = JobCheckpoint.for_job(f"thesis_{scope}", week_key, settings=settings)
    prior_hits = [item for item in _list_scope_snapshots(scope, ckpt.base_dir) if item[0] < week_key]
    if not prior_hits:
        return None
    _, path = prior_hits[-1]
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def persist_thesis_evolution(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not thesis_evolution_enabled(settings) or not checkpoint_enabled(settings):
        return {"skipped": True, "reason": "thesis_evolution or job_checkpoint disabled"}
    scope = str(snapshot.get("scope") or "weekly")
    week_key = str(snapshot.get("week_start") or snapshot.get("week_end") or "default")
    ckpt = JobCheckpoint.for_job(f"thesis_{scope}", week_key, settings=settings)
    prior = _load_prior_snapshot(scope, week_key, settings)
    diff = compute_thesis_diff(snapshot, prior)
    ckpt.save(snapshot)
    return {"snapshot_path": str(ckpt.path), "diff": diff}


def attach_weekly_thesis_evolution(report: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    snapshot = build_weekly_thesis_snapshot(report)
    result = persist_thesis_evolution(snapshot, settings=settings)
    if result.get("skipped"):
        return result
    return result.get("diff") or {}


def attach_forecast_thesis_evolution(
    forecast: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    snapshot = build_forecast_thesis_snapshot(forecast)
    result = persist_thesis_evolution(snapshot, settings=settings)
    if result.get("skipped"):
        return result
    return result.get("diff") or {}


def render_thesis_diff_markdown(diff: dict[str, Any]) -> str:
    if not diff or diff.get("skipped"):
        return ""
    if not diff.get("has_prior"):
        msg = diff.get("message") or "已建立 thesis baseline"
        return f"### 🔄 逻辑演变\n\n- {msg}\n"
    lines = [
        "### 🔄 逻辑演变（相对上期）",
        "",
        f"- 对比区间：**{diff.get('prior_week_start')}~{diff.get('prior_week_end')}** → "
        f"**{diff.get('week_start')}~{diff.get('week_end')}**",
    ]
    if diff.get("themes_added"):
        lines.append(f"- 新增主线：{', '.join(diff['themes_added'][:5])}")
    if diff.get("themes_removed"):
        lines.append(f"- 退出主线：{', '.join(diff['themes_removed'][:5])}")
    if diff.get("themes_kept"):
        lines.append(f"- 延续主线：{', '.join(diff['themes_kept'][:5])}")
    if diff.get("narrative_changed"):
        lines.append("- 叙事摘要：**已变化**")
        if diff.get("prior_narrative_summary"):
            lines.append(f"  - 上期：{diff['prior_narrative_summary']}")
        if diff.get("current_narrative_summary"):
            lines.append(f"  - 本期：{diff['current_narrative_summary']}")
    overlap_delta = diff.get("overlap_delta")
    if overlap_delta not in (None, 0):
        sign = "+" if int(overlap_delta) > 0 else ""
        lines.append(f"- 双源热点重叠 Δ：**{sign}{overlap_delta}**")
    pnl_delta = diff.get("weekly_pnl_pct_delta")
    if pnl_delta is not None and abs(float(pnl_delta)) >= 0.05:
        lines.append(f"- 组合周度收益 Δ：**{float(pnl_delta):+.2f}%**")
    drift = diff.get("drift_score")
    if drift is not None:
        lines.append(f"- 漂移指数：**{drift}**（越高表示 thesis 变化越大）")
    lines.append("")
    return "\n".join(lines).strip()
