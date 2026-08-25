# -*- coding: utf-8
"""L0 → L1 distillation (Phase 2, TencentDB-inspired atoms)."""

from __future__ import annotations

from typing import Any, Optional


def _distill_trade_event(store, event: dict[str, Any]) -> list[int]:
    event_id = int(event["id"])
    payload = event.get("payload") or {}
    at = str(payload.get("at") or event.get("at") or "")
    trade_id = str(payload.get("trade_id") or "")
    created: list[int] = []
    for idx, action in enumerate(payload.get("actions") or []):
        if not isinstance(action, dict):
            continue
        code = str(action.get("code") or "")
        side = str(action.get("side") or "")
        shares = int(action.get("shares") or 0)
        price = float(action.get("price") or 0)
        content = f"{side} {code} {shares}@{price:.2f}"
        if action.get("reasoning"):
            content += f" — {str(action['reasoning'])[:120]}"
        atom_id = store.upsert_l1_atom(
            kind="trade_action",
            code=code,
            at=at,
            title=f"{trade_id} {side}",
            content=content,
            payload={"trade_id": trade_id, "action": action},
            source_event_id=event_id,
            dedupe_key=f"l1:trade:{event_id}:{idx}",
        )
        created.append(atom_id)
    if not created and trade_id:
        atom_id = store.upsert_l1_atom(
            kind="trade_batch",
            at=at,
            title=trade_id,
            content=f"trade batch {trade_id}",
            payload=payload,
            source_event_id=event_id,
            dedupe_key=f"l1:trade_batch:{event_id}",
        )
        created.append(atom_id)
    return created


def _distill_experience_event(store, event: dict[str, Any]) -> list[int]:
    event_id = int(event["id"])
    payload = event.get("payload") or {}
    at = str(payload.get("at") or payload.get("date") or event.get("at") or "")
    code = str(payload.get("code") or "")
    name = str(payload.get("name") or code)
    verdict = str(payload.get("verdict") or "")
    created: list[int] = []

    summary = f"{name} verdict={verdict} mss={payload.get('mss_final')}"
    atom_id = store.upsert_l1_atom(
        kind="experience_summary",
        code=code,
        at=at,
        title=f"close {code}",
        content=summary,
        payload={"verdict": verdict, "mss_final": payload.get("mss_final")},
        source_event_id=event_id,
        dedupe_key=f"l1:experience_summary:{event_id}",
    )
    created.append(atom_id)

    for idx, rule in enumerate(payload.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        text = str(rule.get("text") or rule.get("content") or rule)
        atom_id = store.upsert_l1_atom(
            kind="experience_rule",
            code=code,
            at=at,
            title=str(rule.get("title") or f"rule_{idx + 1}"),
            content=text[:4000],
            payload=rule if isinstance(rule, dict) else {"text": text},
            source_event_id=event_id,
            dedupe_key=f"l1:experience_rule:{event_id}:{idx}",
        )
        created.append(atom_id)
    return created


def _distill_harness_diff_event(store, event: dict[str, Any], *, kind: str) -> list[int]:
    event_id = int(event["id"])
    payload = event.get("payload") or {}
    at = str(payload.get("at") or event.get("at") or "")
    job = str(payload.get("job") or kind)
    ops = payload.get("operations") or {}
    created: list[int] = []
    for op_kind in ("adds", "updates", "deletes"):
        for idx, op in enumerate(ops.get(op_kind) or []):
            if not isinstance(op, dict):
                continue
            overlay = str(op.get("overlay") or op.get("kind") or "")
            key = str(op.get("key") or op.get("entry_id") or "")
            content = f"{op_kind[:-1]} {overlay}/{key}"
            atom_id = store.upsert_l1_atom(
                kind=f"harness_{kind}",
                at=at,
                title=f"{job} {op_kind}",
                content=content,
                payload=op,
                source_event_id=event_id,
                dedupe_key=f"l1:{kind}:{event_id}:{op_kind}:{idx}",
            )
            created.append(atom_id)
    if not created:
        summary = str(payload.get("summary") or payload.get("changes") or job)
        atom_id = store.upsert_l1_atom(
            kind=f"harness_{kind}_summary",
            at=at,
            title=job,
            content=str(summary)[:4000],
            payload=payload,
            source_event_id=event_id,
            dedupe_key=f"l1:{kind}_summary:{event_id}",
        )
        created.append(atom_id)
    return created


def _distill_refinement_event(store, event: dict[str, Any]) -> list[int]:
    event_id = int(event["id"])
    payload = event.get("payload") or {}
    at = str(payload.get("created_at") or payload.get("at") or event.get("at") or "")
    job = str(payload.get("job") or "refine")
    evidence = str(payload.get("evidence") or "")[:4000]
    changes = payload.get("changes") or []
    content = evidence or "; ".join(str(c) for c in changes[:5])
    atom_id = store.upsert_l1_atom(
        kind="harness_refinement",
        at=at,
        title=f"{job} {payload.get('id') or ''}".strip(),
        content=content or job,
        payload={"changes": changes, "evidence": evidence},
        source_event_id=event_id,
        dedupe_key=f"l1:harness_refinement:{event_id}",
    )
    return [atom_id]


def _distill_generic_l0(
    store,
    event: dict[str, Any],
    *,
    kind: str,
    title_fn,
    content_fn,
) -> list[int]:
    event_id = int(event["id"])
    payload = event.get("payload") or {}
    at = str(payload.get("at") or payload.get("date") or payload.get("as_of") or event.get("at") or "")
    atom_id = store.upsert_l1_atom(
        kind=kind,
        code=str(payload.get("code") or ""),
        at=at,
        title=title_fn(payload),
        content=content_fn(payload)[:4000],
        payload=payload,
        source_event_id=event_id,
        dedupe_key=f"l1:{kind}:{event_id}",
    )
    return [atom_id]


def distill_l0_event(store, event: dict[str, Any]) -> list[int]:
    kind = str(event.get("kind") or "")
    if kind == "trade":
        return _distill_trade_event(store, event)
    if kind == "experience":
        return _distill_experience_event(store, event)
    if kind in ("harness_overlay_diff", "harness_memory_diff"):
        return _distill_harness_diff_event(store, event, kind=kind.replace("harness_", ""))
    if kind == "harness_refinement":
        return _distill_refinement_event(store, event)
    if kind == "harness_audit":
        payload = event.get("payload") or {}
        event_id = int(event["id"])
        at = str(payload.get("at") or event.get("at") or "")
        atom_id = store.upsert_l1_atom(
            kind="harness_audit",
            at=at,
            title=str(payload.get("job") or "audit"),
            content=str(payload.get("gate") or payload.get("changes") or "apply audit")[:4000],
            payload=payload,
            source_event_id=event_id,
            dedupe_key=f"l1:harness_audit:{event_id}",
        )
        return [atom_id]
    if kind == "pnl_history":
        return _distill_generic_l0(
            store,
            event,
            kind="pnl_daily",
            title_fn=lambda p: f"pnl {p.get('date')}",
            content_fn=lambda p: f"daily_pnl={p.get('daily_pnl')} cumulative={p.get('cumulative_pnl')}",
        )
    if kind == "capital_event":
        return _distill_generic_l0(
            store,
            event,
            kind="capital_event",
            title_fn=lambda p: f"{p.get('kind')} {p.get('amount')}",
            content_fn=lambda p: f"{p.get('kind')} ¥{p.get('amount')} {p.get('note') or ''}",
        )
    if kind == "intraday_scan":
        return _distill_generic_l0(
            store,
            event,
            kind="intraday_scan",
            title_fn=lambda p: str(p.get("scan_id") or "scan"),
            content_fn=lambda p: f"{p.get('code')} mss={p.get('mss_final')} verdict={p.get('verdict')}",
        )
    if kind == "job_run":
        return _distill_generic_l0(
            store,
            event,
            kind="job_run",
            title_fn=lambda p: str(p.get("job") or "job"),
            content_fn=lambda p: f"{p.get('job')} ok={p.get('success')} date={p.get('date')}",
        )
    if kind == "skill_changelog":
        return _distill_generic_l0(
            store,
            event,
            kind="skill_change",
            title_fn=lambda p: str(p.get("action") or p.get("title") or "skill"),
            content_fn=lambda p: str(p.get("summary") or p.get("title") or p.get("action") or ""),
        )
    if kind == "rejected_strategy":
        return _distill_generic_l0(
            store,
            event,
            kind="rejected_strategy",
            title_fn=lambda p: str(p.get("title") or "rejected"),
            content_fn=lambda p: str(p.get("reason") or ""),
        )
    if kind == "portfolio":
        payload = event.get("payload") or {}
        event_id = int(event["id"])
        at = str(payload.get("at") or event.get("at") or "")
        cash = payload.get("cash")
        total = payload.get("total")
        holdings = payload.get("holdings") or []
        atom_id = store.upsert_l1_atom(
            kind="portfolio_snapshot",
            at=at,
            title=f"portfolio {len(holdings)} holdings",
            content=f"cash={cash} total={total} holdings={len(holdings)}",
            payload={"cash": cash, "total": total, "holdings_count": len(holdings)},
            source_event_id=event_id,
            dedupe_key=f"l1:portfolio:{event_id}",
        )
        return [atom_id]
    return []


def run_distill(
    *,
    limit: int = 500,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.storage import get_store, storage_enabled
    from agent_reach.daily_run.storage.config import distill_settings

    if not storage_enabled(settings):
        return {"skipped": True, "reason": "storage_disabled"}
    cfg = distill_settings(settings)
    if cfg.get("enabled") is False:
        return {"skipped": True, "reason": "distill_disabled"}

    store = get_store(settings)
    event_ids = store.list_undistilled_l0_event_ids(limit=limit)
    distilled_ids: list[int] = []
    atoms_created = 0
    for eid in event_ids:
        event = store.get_l0_event(eid)
        if not event:
            continue
        created = distill_l0_event(store, event)
        if created:
            distilled_ids.append(eid)
            atoms_created += len(created)

    store.mark_l0_distilled(distilled_ids, job="distill")
    return {
        "processed_events": len(distilled_ids),
        "atoms_created": atoms_created,
        "remaining_undistilled": store.status().get("undistilled_l0"),
    }
