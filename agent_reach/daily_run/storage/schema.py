# -*- coding: utf-8
"""SQLite schema migrations for daily-run storage."""

from __future__ import annotations

SCHEMA_VERSION = 2

_V2_TABLES = """
CREATE TABLE IF NOT EXISTS l1_state (
    state_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_state_kind ON l1_state(kind);

CREATE TABLE IF NOT EXISTS l2_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    scenario_key TEXT NOT NULL,
    code TEXT,
    at TEXT NOT NULL,
    title TEXT,
    content TEXT,
    payload_json TEXT NOT NULL,
    source_path TEXT,
    dedupe_key TEXT UNIQUE,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_kind_key ON l2_scenarios(kind, scenario_key);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_at ON l2_scenarios(at);

CREATE TABLE IF NOT EXISTS l3_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    payload_json TEXT,
    version INTEGER DEFAULT 1,
    source_path TEXT,
    dedupe_key TEXT UNIQUE,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l3_documents_kind_key ON l3_documents(kind, doc_key);
"""


def apply_migrations(conn, current_version: int) -> int:
    if current_version < 2:
        conn.executescript(_V2_TABLES)
        conn.execute(
            "INSERT OR REPLACE INTO storage_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        return SCHEMA_VERSION
    return current_version
