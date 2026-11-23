# -*- coding: utf-8
"""Isolate hot_news / 60s native failures on morning + doctor interpretation path."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.hot_news_collector import HotNewsResult, collect_hot_news

_LOCAL_MARKERS = ("127.0.0.1", "localhost")


def morning_doctor_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    sched = (settings or {}).get("schedule") or {}
    if "morning_doctor" in sched:
        return sched.get("morning_doctor") is not False
    return True


def isolation_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    hot = (settings or {}).get("hot_news") or {}
    raw = dict(hot.get("morning_isolation") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "skip_local_when_native_down": raw.get("skip_local_when_native_down", True)
        is not False,
        "local_probe_timeout_seconds": int(raw.get("local_probe_timeout_seconds", 2)),
        "degraded_on_empty": raw.get("degraded_on_empty", True) is not False,
    }


def _is_local_base(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(marker in lowered for marker in _LOCAL_MARKERS)


def effective_hot_news_base_urls(
    base_urls: list[str],
    settings: Optional[dict[str, Any]] = None,
    *,
    workflow: str = "morning",
) -> list[str]:
    """Prefer public 60s when native is down on morning workflow (fast path)."""
    wf = str(workflow or "").lower()
    if wf not in ("morning", "premarket"):
        return list(base_urls)
    iso = isolation_cfg(settings)
    if not iso["enabled"] or not iso["skip_local_when_native_down"]:
        return list(base_urls)

    local = [u for u in base_urls if _is_local_base(u)]
    remote = [u for u in base_urls if not _is_local_base(u)]
    if not local:
        return list(base_urls)

    try:
        from agent_reach.daily_run.hot_news_deploy import native_process_running
    except Exception:
        native_process_running = lambda: False  # noqa: E731

    if native_process_running():
        return list(base_urls)
    if remote:
        return remote
    return ["https://60s.viki.moe"]


def build_hot_news_settings_for_workflow(
    settings: Optional[dict[str, Any]],
    *,
    workflow: str,
) -> dict[str, Any]:
    cfg = dict(settings or {})
    hot = dict(cfg.get("hot_news") or {})
    iso = isolation_cfg(settings)
    wf = str(workflow or "").lower()
    if wf in ("morning", "premarket") and iso["enabled"]:
        hot["base_urls"] = effective_hot_news_base_urls(
            list(hot.get("base_urls") or []),
            settings,
            workflow=workflow,
        )
        hot["local_probe_timeout_seconds"] = iso["local_probe_timeout_seconds"]
    return {**cfg, "hot_news": hot}


def collect_hot_news_isolated(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    workflow: str = "morning",
) -> tuple[HotNewsResult, dict[str, Any]]:
    """Collect hot news; never raise — return meta with status ok|degraded."""
    wf = str(workflow or "").lower()
    iso = isolation_cfg(settings)
    meta: dict[str, Any] = {"workflow": wf, "isolation_enabled": bool(iso["enabled"])}
    if wf in ("morning", "premarket") and iso["enabled"]:
        eff = build_hot_news_settings_for_workflow(settings, workflow=workflow)
        meta["base_urls_effective"] = list((eff.get("hot_news") or {}).get("base_urls") or [])
    else:
        eff = dict(settings or {})

    try:
        result = collect_hot_news(portfolio, settings=eff)
    except Exception as exc:
        meta.update({"status": "degraded", "severity": "warn", "error": str(exc)[:200]})
        return HotNewsResult(), meta

    if result.items or result.daily_headlines or result.platforms_ok:
        meta["status"] = "ok"
        return result, meta

    if wf in ("morning", "premarket") and iso.get("degraded_on_empty"):
        meta.update(
            {
                "status": "degraded",
                "severity": "warn",
                "reason": "60s_unreachable_or_empty",
            }
        )
    else:
        meta["status"] = "ok"
    return result, meta


def hot_news_source_from_result(
    result: HotNewsResult,
    meta: dict[str, Any],
) -> dict[str, Any]:
    if meta.get("status") == "degraded":
        reason = str(meta.get("error") or meta.get("reason") or "60s 不可用")
        return {
            "summary": f"60s 热榜降级（{reason[:80]}）",
            "backend": "60s_api",
            "status": "degraded",
            "severity": meta.get("severity") or "warn",
            "platforms": list(result.platforms_ok or []),
        }
    if not (result.items or result.daily_headlines):
        return {}
    out: dict[str, Any] = {
        "summary": result.summary or result.headline_summary,
        "backend": "60s_api",
        "platforms": result.platforms_ok,
        "text_feed": result.text_feed,
        "status": "ok",
    }
    if result.text_feed:
        out["detail"] = result.text_feed[:2000]
    return out


def summarize_doctor_for_morning(doctor_channels: Optional[dict[str, dict]]) -> list[str]:
    lines: list[str] = []
    for key, info in (doctor_channels or {}).items():
        if not isinstance(info, dict):
            continue
        status = str(info.get("status") or "")
        if status in ("warn", "error"):
            name = str(info.get("name") or key)
            msg = str(info.get("message") or "")[:72]
            lines.append(f"{name}: {msg}" if msg else name)
    return lines[:6]


def generate_morning_narrative_resilient(
    snapshot: dict[str, Any],
    report: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
) -> dict[str, Any]:
    """Morning interpretation (解读) with deterministic fallback — job must continue."""
    from agent_reach.daily_run.report_narrative import (
        _morning_deterministic,
        build_morning_context,
        generate_morning_narrative,
    )

    snap = dict(snapshot)
    if doctor_channels and morning_doctor_enabled(settings):
        warns = summarize_doctor_for_morning(doctor_channels)
        if warns:
            snap["doctor_morning_warnings"] = warns

    try:
        return generate_morning_narrative(snap, report, settings=settings)
    except Exception as exc:
        ctx = build_morning_context(snap, report, settings=settings)
        out = _morning_deterministic(ctx)
        out["job"] = "morning"
        out["skipped"] = False
        out["degraded"] = True
        out["degraded_reason"] = f"interpretation_fallback: {exc}"[:160]
        return out


def generate_merged_morning_narrative_resilient(
    entries: list[tuple],
    *,
    primary_snapshot: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.report_narrative import (
        _merged_morning_deterministic,
        build_merged_morning_context,
        generate_merged_morning_narrative,
    )

    primary = dict(primary_snapshot or {})
    if doctor_channels and morning_doctor_enabled(settings):
        warns = summarize_doctor_for_morning(doctor_channels)
        if warns:
            primary["doctor_morning_warnings"] = warns

    try:
        return generate_merged_morning_narrative(
            entries,
            primary_snapshot=primary,
            settings=settings,
        )
    except Exception as exc:
        ctx = build_merged_morning_context(entries, primary_snapshot=primary)
        out = _merged_morning_deterministic(ctx)
        out["job"] = "morning"
        out["skipped"] = False
        out["degraded"] = True
        out["degraded_reason"] = f"merged_interpretation_fallback: {exc}"[:160]
        return out