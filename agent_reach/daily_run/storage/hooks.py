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


def on_trade_ledger(entry: dict[str, Any], *, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
        return

    def _write() -> None:
        store = get_store()
        store.sync_harness_state(state_payload)

    _safe("harness_state", _write)


def on_harness_diff(diff: dict[str, Any], *, kind: str, source_path: str = "") -> None:
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled():
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
