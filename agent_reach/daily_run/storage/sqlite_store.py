# -*- coding: utf-8
"""SQLite persistence backend for daily-run (Phase 1)."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.storage.base import DailyRunStore
from agent_reach.daily_run.storage.schema import SCHEMA_VERSION, _V2_TABLES, apply_migrations

_SCHEMA_VERSION = SCHEMA_VERSION


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class SqliteDailyRunStore:
    """TencentDB-inspired L0 event log + L1 atoms + materialized portfolio/harness."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS storage_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l0_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    at TEXT NOT NULL,
                    source_path TEXT,
                    payload_json TEXT NOT NULL,
                    dedupe_key TEXT UNIQUE,
                    distilled_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_l0_events_kind_at ON l0_events(kind, at);
                CREATE INDEX IF NOT EXISTS idx_l0_events_distilled ON l0_events(distilled_at);

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    cash REAL,
                    total REAL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_at ON portfolio_snapshots(at);

                CREATE TABLE IF NOT EXISTS positions (
                    code TEXT PRIMARY KEY,
                    name TEXT,
                    shares INTEGER,
                    cost REAL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l1_atoms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    layer TEXT NOT NULL DEFAULT 'L1',
                    kind TEXT NOT NULL,
                    code TEXT,
                    at TEXT NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    payload_json TEXT,
                    source_event_id INTEGER,
                    dedupe_key TEXT UNIQUE,
                    FOREIGN KEY(source_event_id) REFERENCES l0_events(id)
                );
                CREATE INDEX IF NOT EXISTS idx_l1_atoms_kind_at ON l1_atoms(kind, at);
                CREATE INDEX IF NOT EXISTS idx_l1_atoms_code ON l1_atoms(code);

                CREATE TABLE IF NOT EXISTS harness_entries (
                    kind TEXT NOT NULL,
                    entry_id TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    version INTEGER,
                    status TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (kind, entry_id)
                );

                CREATE TABLE IF NOT EXISTS harness_entry_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    entry_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_harness_entry_history_at
                    ON harness_entry_history(kind, entry_id, at);
                """
            )
            conn.executescript(_V2_TABLES)
            conn.execute(
                "INSERT OR IGNORE INTO storage_meta(key, value) VALUES (?, ?)",
                ("schema_version", "1"),
            )
            row = conn.execute(
                "SELECT value FROM storage_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 1
            apply_migrations(conn, current)

    def status(self) -> dict[str, Any]:
        with self._conn() as conn:
            counts = {}
            for table in (
                "l0_events",
                "l1_atoms",
                "l1_state",
                "l2_scenarios",
                "l3_documents",
                "portfolio_snapshots",
                "positions",
                "harness_entries",
                "harness_entry_history",
            ):
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                counts[table] = int(row["c"]) if row else 0
            undistilled = conn.execute(
                "SELECT COUNT(*) AS c FROM l0_events WHERE distilled_at IS NULL"
            ).fetchone()
            schema = conn.execute(
                "SELECT value FROM storage_meta WHERE key = 'schema_version'"
            ).fetchone()
        return {
            "backend": "sqlite",
            "path": str(self.path),
            "schema_version": int((schema["value"] if schema else _SCHEMA_VERSION)),
            "counts": counts,
            "undistilled_l0": int(undistilled["c"]) if undistilled else 0,
        }

    def append_l0_event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        at: str = "",
        source_path: str = "",
        dedupe_key: str = "",
    ) -> int:
        event_at = at or str(payload.get("at") or _now_iso())
        with self._conn() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM l0_events WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO l0_events(kind, at, source_path, payload_json, dedupe_key)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    event_at,
                    source_path or None,
                    _json_dumps(payload),
                    dedupe_key or None,
                ),
            )
            return int(cur.lastrowid)

    def upsert_portfolio(
        self,
        portfolio: dict[str, Any],
        *,
        source: str = "save",
        at: str = "",
    ) -> int:
        event_at = at or _now_iso()
        cash = float(portfolio.get("cash") or 0)
        total = float(portfolio.get("total") or 0)
        payload_json = _json_dumps(portfolio)
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO portfolio_snapshots(at, source, cash, total, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_at, source, cash, total, payload_json),
            )
            snap_id = int(cur.lastrowid)
            for holding in portfolio.get("holdings") or []:
                if not isinstance(holding, dict):
                    continue
                code = str(holding.get("code") or "").strip()
                if not code:
                    continue
                conn.execute(
                    """
                    INSERT INTO positions(code, name, shares, cost, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name=excluded.name,
                        shares=excluded.shares,
                        cost=excluded.cost,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        code,
                        str(holding.get("name") or ""),
                        int(holding.get("shares") or 0),
                        float(holding.get("cost") or 0),
                        _json_dumps(holding),
                        event_at,
                    ),
                )
            return snap_id

    def sync_harness_state(self, state_payload: dict[str, Any], *, at: str = "") -> None:
        event_at = at or str(state_payload.get("updated_at") or _now_iso())
        entries = state_payload.get("entries") or {}
        with self._conn() as conn:
            if not isinstance(entries, dict):
                return
            for kind, bucket in entries.items():
                if not isinstance(bucket, dict):
                    continue
                for entry_id, raw in bucket.items():
                    if not isinstance(raw, dict):
                        continue
                    conn.execute(
                        """
                        INSERT INTO harness_entries(
                            kind, entry_id, title, content, version, status, payload_json, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(kind, entry_id) DO UPDATE SET
                            title=excluded.title,
                            content=excluded.content,
                            version=excluded.version,
                            status=excluded.status,
                            payload_json=excluded.payload_json,
                            updated_at=excluded.updated_at
                        """,
                        (
                            str(kind),
                            str(entry_id),
                            str(raw.get("title") or entry_id),
                            str(raw.get("content") or ""),
                            int(raw.get("version") or 1),
                            str(raw.get("status") or ""),
                            _json_dumps(raw),
                            str(raw.get("updated_at") or event_at),
                        ),
                    )

    def append_harness_entry_history(
        self,
        *,
        kind: str,
        entry_id: str,
        action: str,
        payload: dict[str, Any],
        at: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO harness_entry_history(kind, entry_id, action, at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, entry_id, action, at or _now_iso(), _json_dumps(payload)),
            )

    def upsert_l1_atom(
        self,
        *,
        kind: str,
        content: str,
        at: str = "",
        code: str = "",
        title: str = "",
        payload: Optional[dict[str, Any]] = None,
        source_event_id: Optional[int] = None,
        dedupe_key: str = "",
    ) -> int:
        atom_at = at or _now_iso()
        with self._conn() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM l1_atoms WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO l1_atoms(
                    layer, kind, code, at, title, content, payload_json, source_event_id, dedupe_key
                ) VALUES ('L1', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    code or None,
                    atom_at,
                    title or None,
                    content,
                    _json_dumps(payload or {}),
                    source_event_id,
                    dedupe_key or None,
                ),
            )
            return int(cur.lastrowid)

    def upsert_l1_state(
        self,
        state_key: str,
        kind: str,
        payload: dict[str, Any],
        *,
        at: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO l1_state(state_key, kind, at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    kind=excluded.kind,
                    at=excluded.at,
                    payload_json=excluded.payload_json
                """,
                (state_key, kind, at or _now_iso(), _json_dumps(payload)),
            )

    def upsert_l2_scenario(
        self,
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
    ) -> int:
        event_at = at or str(payload.get("at") or payload.get("date") or _now_iso())
        with self._conn() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM l2_scenarios WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if existing:
                    row_id = int(existing["id"])
                    conn.execute(
                        """
                        UPDATE l2_scenarios SET
                            kind=?, scenario_key=?, code=?, at=?, title=?, content=?,
                            payload_json=?, source_path=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            kind,
                            scenario_key,
                            code or None,
                            event_at,
                            title or None,
                            content or None,
                            _json_dumps(payload),
                            source_path or None,
                            _now_iso(),
                            row_id,
                        ),
                    )
                    return row_id
            cur = conn.execute(
                """
                INSERT INTO l2_scenarios(
                    kind, scenario_key, code, at, title, content,
                    payload_json, source_path, dedupe_key, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    scenario_key,
                    code or None,
                    event_at,
                    title or None,
                    content or None,
                    _json_dumps(payload),
                    source_path or None,
                    dedupe_key or None,
                    _now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def upsert_l3_document(
        self,
        kind: str,
        doc_key: str,
        content: str,
        *,
        title: str = "",
        payload: Optional[dict[str, Any]] = None,
        source_path: str = "",
        dedupe_key: str = "",
        version: int = 1,
    ) -> int:
        with self._conn() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM l3_documents WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE l3_documents SET
                            title=?, content=?, payload_json=?, version=?, source_path=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            title or None,
                            content,
                            _json_dumps(payload or {}),
                            int(version),
                            source_path or None,
                            _now_iso(),
                            int(existing["id"]),
                        ),
                    )
                    return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO l3_documents(
                    kind, doc_key, title, content, payload_json, version, source_path, dedupe_key, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    doc_key,
                    title or None,
                    content,
                    _json_dumps(payload or {}),
                    int(version),
                    source_path or None,
                    dedupe_key or None,
                    _now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def get_l0_event(self, event_id: int) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, kind, at, source_path, payload_json, dedupe_key, distilled_at
                FROM l0_events WHERE id = ?
                """,
                (int(event_id),),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        return {
            "id": row["id"],
            "kind": row["kind"],
            "at": row["at"],
            "source_path": row["source_path"],
            "payload": payload,
            "dedupe_key": row["dedupe_key"],
            "distilled_at": row["distilled_at"],
        }

    def query_l0_events(
        self,
        *,
        kind: str = "",
        since: str = "",
        until: str = "",
        limit: int = 50,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if since:
            clauses.append("at >= ?")
            params.append(since)
        if until:
            clauses.append("at < ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_sql = "ASC, id ASC" if str(order).lower() == "asc" else "DESC, id DESC"
        params.append(max(1, int(limit)))
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, kind, at, source_path, payload_json, dedupe_key, distilled_at
                FROM l0_events
                {where}
                ORDER BY at {order_sql}
                LIMIT ?
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "at": row["at"],
                    "source_path": row["source_path"],
                    "payload": payload,
                    "dedupe_key": row["dedupe_key"],
                    "distilled_at": row["distilled_at"],
                }
            )
        return out

    def query_l1_atoms(
        self,
        *,
        kind: str = "",
        code: str = "",
        since: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if code:
            clauses.append("code = ?")
            params.append(code)
        if since:
            clauses.append("at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, kind, code, at, title, content, payload_json, source_event_id, dedupe_key
                FROM l1_atoms
                {where}
                ORDER BY at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "code": row["code"],
                    "at": row["at"],
                    "title": row["title"],
                    "content": row["content"],
                    "payload": payload,
                    "source_event_id": row["source_event_id"],
                    "dedupe_key": row["dedupe_key"],
                }
            )
        return out

    def query_trades(
        self,
        *,
        code: str = "",
        since: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = self.query_l0_events(kind="trade", since=since, limit=max(limit * 2, 50))
        out: list[dict[str, Any]] = []
        code_norm = code.strip()
        for event in events:
            payload = event.get("payload") or {}
            actions = payload.get("actions") or []
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_code = str(action.get("code") or "")
                if code_norm and action_code != code_norm:
                    continue
                out.append(
                    {
                        "at": payload.get("at") or event.get("at"),
                        "trade_id": payload.get("trade_id"),
                        "decision_action": payload.get("decision_action"),
                        "action": action,
                        "event_id": event.get("id"),
                    }
                )
                if len(out) >= limit:
                    return out
        return out

    def list_undistilled_l0_event_ids(self, *, limit: int = 500) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id FROM l0_events
                WHERE distilled_at IS NULL
                ORDER BY id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def mark_l0_distilled(self, event_ids: list[int], *, job: str = "distill") -> None:
        if not event_ids:
            return
        stamp = _now_iso()
        with self._conn() as conn:
            conn.executemany(
                "UPDATE l0_events SET distilled_at = ? WHERE id = ?",
                [(stamp, int(eid)) for eid in event_ids],
            )
            conn.execute(
                "INSERT OR REPLACE INTO storage_meta(key, value) VALUES (?, ?)",
                (f"last_{job}_at", stamp),
            )

    def prune_distilled_l0(
        self,
        *,
        cutoff_iso: str,
        kinds: list[str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        kinds_norm = [str(k).strip() for k in kinds if str(k).strip()]
        if not kinds_norm:
            return {"deleted_rows": 0, "bytes_estimate": 0, "by_kind": {}}
        placeholders = ",".join("?" for _ in kinds_norm)
        params = kinds_norm + [cutoff_iso]
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT kind, COUNT(*) AS c, SUM(length(payload_json)) AS bytes
                FROM l0_events
                WHERE kind IN ({placeholders})
                  AND distilled_at IS NOT NULL
                  AND at < ?
                GROUP BY kind
                """,
                params,
            ).fetchall()
            by_kind = {
                str(row["kind"]): {"rows": int(row["c"]), "bytes": int(row["bytes"] or 0)}
                for row in rows
            }
            total_rows = sum(v["rows"] for v in by_kind.values())
            total_bytes = sum(v["bytes"] for v in by_kind.values())
            if not dry_run and total_rows > 0:
                conn.execute(
                    f"""
                    DELETE FROM l0_events
                    WHERE kind IN ({placeholders})
                      AND distilled_at IS NOT NULL
                      AND at < ?
                    """,
                    params,
                )
        return {
            "cutoff_iso": cutoff_iso,
            "kinds": kinds_norm,
            "dry_run": dry_run,
            "deleted_rows": 0 if dry_run else total_rows,
            "would_delete_rows": total_rows,
            "bytes_estimate": total_bytes,
            "by_kind": by_kind,
        }

    def query_trade_ledger_entries(
        self,
        *,
        since: str = "",
        until: str = "",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        events = self.query_l0_events(
            kind="trade",
            since=since,
            until=until,
            limit=limit,
            order="asc",
        )
        return [dict(event.get("payload") or {}) for event in events if event.get("payload")]

    def query_pnl_history_records(
        self,
        *,
        since: str = "",
        until: str = "",
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        events = self.query_l0_events(
            kind="pnl_history",
            since=since,
            until=until,
            limit=limit,
            order="asc",
        )
        return [dict(event.get("payload") or {}) for event in events if event.get("payload")]

    def query_latest_portfolio_snapshot(self) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT payload_json, at, source FROM portfolio_snapshots
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            payload.setdefault("_snapshot_at", row["at"])
            payload.setdefault("_snapshot_source", row["source"])
        return payload

    def query_l1_state(
        self,
        *,
        state_key: str = "",
        kind: str = "",
    ) -> Optional[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if state_key:
            clauses.append("state_key = ?")
            params.append(state_key)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT state_key, kind, at, payload_json FROM l1_state {where} LIMIT 1",
                params,
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            payload.setdefault("_state_key", row["state_key"])
            payload.setdefault("_state_kind", row["kind"])
            payload.setdefault("_state_at", row["at"])
        return payload

    def query_l2_scenarios(
        self,
        *,
        kind: str = "",
        scenario_key: str = "",
        code: str = "",
        since: str = "",
        until: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if scenario_key:
            clauses.append("scenario_key = ?")
            params.append(scenario_key)
        if code:
            clauses.append("code = ?")
            params.append(code)
        if since:
            clauses.append("at >= ?")
            params.append(since)
        if until:
            clauses.append("at < ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, kind, scenario_key, code, at, title, content, payload_json, source_path
                FROM l2_scenarios
                {where}
                ORDER BY at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "scenario_key": row["scenario_key"],
                    "code": row["code"],
                    "at": row["at"],
                    "title": row["title"],
                    "content": row["content"],
                    "payload": payload,
                    "source_path": row["source_path"],
                }
            )
        return out

    def get_l3_document(self, kind: str, doc_key: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT kind, doc_key, title, content, payload_json, version, source_path, updated_at
                FROM l3_documents
                WHERE kind = ? AND doc_key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (kind, doc_key),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        return {
            "kind": row["kind"],
            "doc_key": row["doc_key"],
            "title": row["title"],
            "content": row["content"],
            "payload": payload,
            "version": row["version"],
            "source_path": row["source_path"],
            "updated_at": row["updated_at"],
        }

    def list_harness_entries(self, *, kind: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT kind, entry_id, title, content, version, status, payload_json, updated_at
                FROM harness_entries
                {where}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "kind": row["kind"],
                    "entry_id": row["entry_id"],
                    "title": row["title"],
                    "content": row["content"],
                    "version": row["version"],
                    "status": row["status"],
                    "payload": payload,
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def vacuum(self) -> None:
        with self._conn() as conn:
            conn.execute("VACUUM")


def open_sqlite_store(path: Path) -> DailyRunStore:
    return SqliteDailyRunStore(path)
