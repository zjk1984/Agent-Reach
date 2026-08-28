# -*- coding: utf-8
"""Best-effort dual-write hooks into daily-run storage."""

from __future__ import annotations

from typing import Any, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run.storage.hooks")


def _safe(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        logger.warning("daily-run storage {} failed: {}", label, exc)


def _allow_storage_write(
    *,
    kind: str,
    payload: Any = None,
    source: str = "",
    settings: Optional[dict[str, Any]] = None,
) -> bool:
    from agent_reach.daily_run.storage.guard import storage_write_blocked_reason

    reason = storage_write_blocked_reason(
        settings,
        kind=kind,
        payload=payload,
        source=source,
    )
    if reason == "storage_disabled":
        return False
    if reason:
        logger.warning("daily-run storage write blocked ({}): {}", reason, kind)
        return False
    return True


def on_trade_ledger(entry: dict[str, Any], *, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="trade", payload=entry):
        return
    at = str(entry.get("at") or "")
    trade_id = str(entry.get("trade_id") or "")
    dedupe = f"trade:{at}:{trade_id}" if at and trade_id else f"trade:{at or 'unknown'}"

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            "trade",
            entry,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe,
        )

    _safe("trade", _write)


def on_portfolio_save(portfolio: dict[str, Any], *, source: str = "save") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="portfolio", payload=portfolio, source=source):
        return

    def _write() -> None:
        store = get_store()
        snap_id = store.upsert_portfolio(portfolio, source=source)
        store.append_l0_event(
            "portfolio",
            {
                "source": source,
                "snapshot_id": snap_id,
                "cash": portfolio.get("cash"),
                "total": portfolio.get("total"),
                "holdings_count": len(portfolio.get("holdings") or []),
            },
        )

    _safe("portfolio", _write)


def on_experience_entry(entry: dict[str, Any], *, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="experience", payload=entry):
        return
    at = str(entry.get("at") or entry.get("date") or "")
    code = str(entry.get("code") or "")
    dedupe = f"experience:{at}:{code}" if at and code else f"experience:{at}"

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            "experience",
            entry,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe,
        )

    _safe("experience", _write)


def on_harness_refinement(event: dict[str, Any], *, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="harness_refinement", payload=event):
        return
    event_id = str(event.get("id") or "")
    at = str(event.get("created_at") or "")
    dedupe = f"harness_refinement:{event_id}" if event_id else f"harness_refinement:{at}"

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            "harness_refinement",
            event,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe,
        )
        for edit in event.get("edits") or []:
            if not isinstance(edit, dict):
                continue
            store.append_harness_entry_history(
                kind=str(edit.get("kind") or ""),
                entry_id=str(edit.get("entry_id") or ""),
                action=str(edit.get("action") or "update"),
                payload=edit,
                at=at,
            )

    _safe("harness_refinement", _write)


def on_harness_state_save(state_payload: dict[str, Any]) -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="harness_state", payload=state_payload):
        return

    def _write() -> None:
        store = get_store()
        store.sync_harness_state(state_payload)
        sync_l3_policy_persona(state_payload)

    _safe("harness_state", _write)


def on_harness_diff(diff: dict[str, Any], *, kind: str, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind=kind, payload=diff):
        return
    at = str(diff.get("at") or "")
    job = str(diff.get("job") or kind)
    dedupe = f"{kind}:{at}:{job}:{diff.get('refinement_id') or ''}"

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            kind,
            diff,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe,
        )

    _safe(kind, _write)


def on_apply_audit(event: dict[str, Any], *, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="harness_audit", payload=event):
        return
    at = str(event.get("at") or "")
    job = str(event.get("job") or "apply")
    dedupe = f"harness_audit:{at}:{job}"

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            "harness_audit",
            event,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe,
        )

    _safe("harness_audit", _write)


def maybe_auto_distill(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.storage.config import distill_settings, storage_enabled
    from agent_reach.daily_run.storage.distill import run_distill

    if not storage_enabled(settings):
        return {"skipped": True, "reason": "storage_disabled"}
    cfg = distill_settings(settings)
    if not cfg.get("auto_after_close"):
        return {"skipped": True, "reason": "auto_after_close_disabled"}
    return run_distill(settings=settings)


def on_l0_event(
    kind: str,
    payload: dict[str, Any],
    *,
    at: str = "",
    source_path: str = "",
    dedupe_key: str = "",
) -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind=kind, payload=payload):
        return

    def _write() -> None:
        store = get_store()
        store.append_l0_event(
            kind,
            payload,
            at=at,
            source_path=source_path,
            dedupe_key=dedupe_key,
        )

    _safe(kind, _write)


def on_l1_state(state_key: str, kind: str, payload: dict[str, Any], *, at: str = "") -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind=kind, payload=payload):
        return

    def _write() -> None:
        get_store().upsert_l1_state(state_key, kind, payload, at=at)

    _safe(f"l1_state:{kind}", _write)


def on_l2_scenario(
    kind: str,
    scenario_key: str,
    payload: dict[str, Any],
    *,
    code: str = "",
    at: str = "",
    title: str = "",
    content: str = "",
    source_path: str = "",
    dedupe_key: str = "",
) -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind=kind, payload=payload):
        return

    def _write() -> None:
        get_store().upsert_l2_scenario(
            kind,
            scenario_key,
            payload,
            code=code,
            at=at,
            title=title,
            content=content,
            source_path=source_path,
            dedupe_key=dedupe_key or f"l2:{kind}:{scenario_key}",
        )

    _safe(f"l2:{kind}", _write)


def on_l3_document(
    kind: str,
    doc_key: str,
    content: str,
    *,
    title: str = "",
    payload: Optional[dict[str, Any]] = None,
    source_path: str = "",
    dedupe_key: str = "",
    version: int = 1,
) -> None:
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind=kind, payload=payload or {"content": content}):
        return

    def _write() -> None:
        get_store().upsert_l3_document(
            kind,
            doc_key,
            content,
            title=title,
            payload=payload,
            source_path=source_path,
            dedupe_key=dedupe_key or f"l3:{kind}:{doc_key}",
            version=version,
        )

    _safe(f"l3:{kind}", _write)


def on_daily_pnl(record: dict[str, Any], *, source_path: str = "") -> None:
    at = str(record.get("recorded_at") or record.get("date") or "")
    dedupe = f"pnl_history:{record.get('date')}"
    on_l0_event("pnl_history", record, at=at, source_path=source_path, dedupe_key=dedupe)


def on_capital_event(event: dict[str, Any], *, source_path: str = "") -> None:
    at = str(event.get("at") or event.get("date") or "")
    dedupe = f"capital:{at}:{event.get('kind')}:{event.get('amount')}"
    on_l0_event("capital_event", event, at=at, source_path=source_path, dedupe_key=dedupe)


def on_intraday_scan(entry: dict[str, Any], *, code: str = "", source_path: str = "") -> None:
    at = str(entry.get("as_of") or "")
    scan_id = str(entry.get("scan_id") or "")
    sym = code or str(entry.get("code") or "")
    dedupe = f"intraday_scan:{sym}:{scan_id}:{at}"
    on_l0_event("intraday_scan", entry, at=at, source_path=source_path, dedupe_key=dedupe)


def on_intraday_state(state: dict[str, Any], *, code: str = "", source_path: str = "") -> None:
    day = str(state.get("date") or "")
    sym = code or "global"
    key = f"{sym}/{day}"
    on_l2_scenario(
        "intraday_state",
        key,
        state,
        code=sym if sym != "global" else "",
        at=day,
        title=f"intraday {sym} {day}",
        content=f"scans={len(state.get('scans') or [])} trades={len(state.get('trades') or [])}",
        source_path=source_path,
        dedupe_key=f"l2:intraday_state:{key}",
    )


def on_job_run(manifest: dict[str, Any], *, source_path: str = "") -> None:
    at = str(manifest.get("finished_at") or manifest.get("started_at") or "")
    job = str(manifest.get("job") or "")
    day = str(manifest.get("date") or "")
    dedupe = f"job_run:{day}:{job}:{manifest.get('manifest_id') or source_path}"
    on_l0_event("job_run", manifest, at=at, source_path=source_path, dedupe_key=dedupe)


def on_skill_changelog(event: dict[str, Any], *, source_path: str = "") -> None:
    at = str(event.get("at") or "")
    dedupe = f"skill_changelog:{at}:{event.get('action') or event.get('title') or ''}"
    on_l0_event("skill_changelog", event, at=at, source_path=source_path, dedupe_key=dedupe)


def on_rejected_strategy(record: dict[str, Any], *, source_path: str = "") -> None:
    at = str(record.get("created_at") or "")
    dedupe = f"rejected:{record.get('id') or at}"
    on_l0_event("rejected_strategy", record, at=at, source_path=source_path, dedupe_key=dedupe)


def on_trade_case(
    case_id: str,
    trade_record: dict[str, Any],
    *,
    abstract: str = "",
    overview: str = "",
    source_path: str = "",
) -> None:
    code = str(trade_record.get("code") or "")
    at = str(trade_record.get("as_of") or "")
    from agent_reach.daily_run.storage import get_store

    if not _allow_storage_write(kind="trade_case", payload=trade_record):
        return

    def _write() -> None:
        store = get_store()
        store.upsert_l1_atom(
            kind="trade_case",
            code=code,
            at=at,
            title=case_id,
            content=abstract or overview or str(trade_record.get("portfolio_message") or "")[:4000],
            payload={"case_id": case_id, "record": trade_record, "overview": overview[:4000]},
            dedupe_key=f"l1:trade_case:{case_id}",
        )
        store.upsert_l2_scenario(
            "trade_case",
            case_id,
            trade_record,
            code=code,
            at=at,
            title=case_id,
            content=overview[:4000] if overview else abstract[:4000],
            source_path=source_path,
            dedupe_key=f"l2:trade_case:{case_id}",
        )

    _safe("trade_case", _write)


def on_rules_summary(summary: dict[str, Any], *, source_path: str = "") -> None:
    on_l1_state("experience:rules_summary", "rules_summary", summary, at=str(summary.get("updated_at") or ""))


def on_runtime_overlay(overlay: dict[str, Any], *, source_path: str = "") -> None:
    on_l2_scenario(
        "runtime_overlay",
        "effective",
        overlay,
        at=str(overlay.get("updated_at") or ""),
        title="runtime overlay",
        content="effective harness runtime overlay",
        source_path=source_path,
        dedupe_key="l2:runtime_overlay:effective",
    )


def on_last_snapshot(payload: dict[str, Any], *, source_path: str = "") -> None:
    at = str(payload.get("as_of") or payload.get("generated_at") or "")[:10]
    on_l1_state("last_snapshot", "last_snapshot", payload, at=at)


def on_daily_cache(payload: dict[str, Any], *, day: str, source_path: str = "") -> None:
    day_key = str(day or "")[:10]
    if not day_key:
        return
    on_l1_state(f"daily_cache:{day_key}", "daily_cache", payload, at=day_key)


def _baseline_event_at(record: dict[str, Any]) -> str:
    """Prefer full timestamps so same-day baseline saves sort newest-first."""
    for key in ("baseline_saved_at", "as_of", "close_date", "date"):
        val = record.get(key)
        if val:
            return str(val)
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _baseline_day_key(record: dict[str, Any]) -> str:
    for key in ("close_date", "date", "as_of", "baseline_saved_at"):
        val = record.get(key)
        if val:
            return str(val)[:10]
    return ""


def on_baseline(kind: str, code: str, record: dict[str, Any], *, source_path: str = "") -> None:
    day = _baseline_day_key(record)
    key = f"{kind}/{code}"
    on_l2_scenario(
        f"baseline_{kind}",
        key,
        record,
        code=code,
        at=_baseline_event_at(record),
        title=f"{kind} baseline {code}",
        content=f"mss={record.get('mss_final') or record.get('mss')}",
        source_path=source_path,
        dedupe_key=f"l2:baseline:{kind}:{code}:{day}",
    )


def on_market_review(review: dict[str, Any], *, review_date: str = "", source_path: str = "") -> None:
    day = review_date or str(review.get("date") or "")
    on_l2_scenario(
        "market_review",
        day,
        review,
        at=day,
        title=f"market review {day}",
        content=str(review.get("summary") or review.get("headline") or "")[:4000],
        source_path=source_path,
        dedupe_key=f"l2:market_review:{day}",
    )


def on_forecast(forecast: dict[str, Any], *, source_path: str = "") -> None:
    ws = str(forecast.get("week_start") or "")
    on_l2_scenario(
        "forecast",
        ws,
        forecast,
        at=ws,
        title=f"week forecast {ws}",
        content=str(forecast.get("summary") or "")[:4000],
        source_path=source_path,
        dedupe_key=f"l2:forecast:{ws}",
    )


def on_harness_snapshot(payload: dict[str, Any], *, snapshot_path: str = "") -> None:
    name = snapshot_path.rsplit("/", 1)[-1] if snapshot_path else "snapshot"
    on_l2_scenario(
        "harness_snapshot",
        name,
        payload,
        at=str(payload.get("created_at") or ""),
        title=name,
        content=str(payload.get("job") or ""),
        source_path=snapshot_path,
        dedupe_key=f"l2:harness_snapshot:{name}",
    )


def on_skill_fragment(name: str, content: str, *, source_path: str = "") -> None:
    on_l3_document(
        f"skill_{name}",
        name,
        content,
        title=name,
        source_path=source_path,
        dedupe_key=f"l3:skill:{name}",
    )


def sync_l3_policy_persona(state_payload: dict[str, Any]) -> None:
    """L3: distill harness policy entries into a persona document."""
    entries = (state_payload.get("entries") or {}).get("policy") or {}
    if not isinstance(entries, dict) or not entries:
        return
    lines = ["# Harness Policy Persona", ""]
    for entry in sorted(entries.values(), key=lambda e: str(e.get("updated_at") or ""), reverse=True):
        if not isinstance(entry, dict):
            continue
        lines.append(f"- **{entry.get('title') or entry.get('id')}**: {entry.get('content')}")
    content = "\n".join(lines).strip()
    on_l3_document(
        "policy_persona",
        "harness_policy",
        content,
        title="Harness Policy Persona",
        payload={"entry_count": len(entries)},
        dedupe_key="l3:policy_persona:harness_policy",
    )

