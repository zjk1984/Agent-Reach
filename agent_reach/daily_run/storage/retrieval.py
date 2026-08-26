# -*- coding: utf-8
"""Retrieve L1 atoms / trades from daily-run storage for LLM prompts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from agent_reach.daily_run.storage.config import retrieval_settings, storage_enabled


def _normalize_code(raw: Any) -> str:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    return _normalize_code(str(raw or ""))


def _retrieval_enabled(settings: Optional[dict[str, Any]], *, job: str = "") -> bool:
    if not storage_enabled(settings):
        return False
    cfg = retrieval_settings(settings)
    if cfg.get("enabled") is False:
        return False
    jobs = cfg.get("llm_jobs") or {}
    if job:
        key = str(job).strip()
        if key in jobs and jobs[key] is False:
            return False
        if ":" in key:
            base = key.split(":", 1)[0]
            if base in jobs and jobs[base] is False:
                return False
    return True


def extract_symbol_codes(*sources: Any) -> list[str]:
    """Collect normalized A-share codes from nested snapshot/report/evidence dicts."""
    codes: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        code = _normalize_code(raw)
        if not code or code in seen:
            return
        seen.add(code)
        codes.append(code)

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 6 or obj is None:
            return
        if isinstance(obj, dict):
            if "code" in obj:
                add(obj.get("code"))
            for key in ("holdings", "watchlist", "symbols", "entries", "rows", "actions"):
                block = obj.get(key)
                if isinstance(block, list):
                    for item in block:
                        if isinstance(item, dict):
                            add(item.get("code"))
                        elif isinstance(item, (list, tuple)) and len(item) >= 2:
                            add(item[1])
            for key, value in obj.items():
                if key in ("code", "holdings", "watchlist", "symbols", "entries", "rows", "actions"):
                    continue
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(obj, list):
            for item in obj[:40]:
                walk(item, depth + 1)

    for src in sources:
        walk(src)
    return codes


def _since_iso(settings: Optional[dict[str, Any]]) -> str:
    cfg = retrieval_settings(settings)
    days = max(1, int(cfg.get("lookback_days") or 30))
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _compact_line(text: Any, *, max_chars: int) -> str:
    raw = str(text or "").strip().replace("\n", " ")
    if len(raw) <= max_chars:
        return raw
    return raw[: max(0, max_chars - 1)].rstrip() + "…"


def build_storage_retrieval_context(
    *,
    settings: Optional[dict[str, Any]] = None,
    codes: Optional[list[str]] = None,
    job: str = "",
    sources: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Query SQLite/Postgres for compact trade/experience atoms relevant to LLM jobs."""
    if not _retrieval_enabled(settings, job=job):
        return {}

    cfg = retrieval_settings(settings)
    resolved_codes = list(codes or [])
    if not resolved_codes and sources:
        resolved_codes = extract_symbol_codes(*sources)
    max_codes = max(1, int(cfg.get("max_codes") or 8))
    resolved_codes = resolved_codes[:max_codes]

    since = _since_iso(settings)
    max_atoms = max(1, int(cfg.get("max_atoms_per_code") or 4))
    max_trades = max(1, int(cfg.get("max_trades") or 15))
    max_line = max(48, int(cfg.get("max_line_chars") or 120))
    atom_kinds = cfg.get("atom_kinds") or [
        "trade_action",
        "experience_summary",
        "experience_rule",
        "trade_batch",
    ]
    kind_set = {str(k).strip() for k in atom_kinds if str(k).strip()}

    try:
        from agent_reach.daily_run.storage import get_store

        store = get_store(settings)
    except Exception:
        return {}

    atoms_out: list[dict[str, Any]] = []
    for code in resolved_codes:
        rows = store.query_l1_atoms(code=code, since=since, limit=max_atoms * 3)
        kept = 0
        for row in rows:
            kind = str(row.get("kind") or "")
            if kind_set and kind not in kind_set:
                continue
            atoms_out.append(
                {
                    "code": row.get("code") or code,
                    "kind": kind,
                    "at": row.get("at"),
                    "line": _compact_line(row.get("content") or row.get("title"), max_chars=max_line),
                }
            )
            kept += 1
            if kept >= max_atoms:
                break

    trades_out: list[dict[str, Any]] = []
    if cfg.get("include_trades", True) is not False:
        code_filter = resolved_codes[0] if len(resolved_codes) == 1 else ""
        trade_rows = store.query_trades(code=code_filter, since=since, limit=max_trades)
        for row in trade_rows:
            action = row.get("action") or {}
            code = _normalize_code(action.get("code"))
            if resolved_codes and code and code not in resolved_codes:
                continue
            side = str(action.get("side") or "")
            shares = int(action.get("shares") or 0)
            price = float(action.get("price") or 0)
            line = f"{side} {code} {shares}@{price:.2f}"
            reasoning = str(action.get("reasoning") or "").strip()
            if reasoning:
                line += f" — {_compact_line(reasoning, max_chars=max_line // 2)}"
            trades_out.append(
                {
                    "at": row.get("at"),
                    "trade_id": row.get("trade_id"),
                    "code": code,
                    "line": line,
                }
            )
            if len(trades_out) >= max_trades:
                break

    if not atoms_out and not trades_out:
        return {}

    return {
        "lookback_days": int(cfg.get("lookback_days") or 30),
        "codes": resolved_codes,
        "atoms": atoms_out,
        "trades": trades_out,
    }


def attach_storage_retrieval(
    payload: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    job: str = "",
    extra_sources: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Return payload copy with ``storage_retrieval`` block when DB has relevant history."""
    sources = [payload]
    if extra_sources:
        sources.extend(extra_sources)
    block = build_storage_retrieval_context(
        settings=settings,
        codes=extract_symbol_codes(*sources),
        job=job,
        sources=sources,
    )
    if not block:
        return payload
    out = dict(payload)
    out["storage_retrieval"] = block
    return out
