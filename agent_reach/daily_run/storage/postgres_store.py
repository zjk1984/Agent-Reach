# -*- coding: utf-8
"""Postgres / TencentDB Cloud backend stub (Phase 3)."""

from __future__ import annotations

from typing import Any

from agent_reach.daily_run.storage.base import DailyRunStore


class PostgresDailyRunStore:
    """Placeholder for remote Postgres/TDSQL deployment."""

    def __init__(self, dsn: str, *, schema: str = "daily_run") -> None:
        self.dsn = dsn
        self.schema = schema

    def _raise(self) -> None:
        raise NotImplementedError(
            "Postgres backend is Phase 3. Set storage.backend=sqlite for local dual-write, "
            "or implement PostgresDailyRunStore against your DSN."
        )

    def status(self) -> dict[str, Any]:
        return {
            "backend": "postgres",
            "dsn": self.dsn.split("@")[-1] if "@" in self.dsn else "(configured)",
            "schema": self.schema,
            "ready": False,
            "message": "Phase 3 stub — use sqlite backend or extend this class.",
        }

    def append_l0_event(self, kind: str, payload: dict[str, Any], **kwargs: Any) -> int:
        self._raise()
        return 0

    def upsert_portfolio(self, portfolio: dict[str, Any], **kwargs: Any) -> int:
        self._raise()
        return 0

    def sync_harness_state(self, state_payload: dict[str, Any], **kwargs: Any) -> None:
        self._raise()

    def append_harness_entry_history(self, **kwargs: Any) -> None:
        self._raise()

    def upsert_l1_atom(self, **kwargs: Any) -> int:
        self._raise()
        return 0

    def get_l0_event(self, event_id: int) -> dict[str, Any] | None:
        self._raise()
        return None

    def query_l0_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._raise()
        return []

    def query_l1_atoms(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._raise()
        return []

    def query_trades(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._raise()
        return []

    def list_undistilled_l0_event_ids(self, **kwargs: Any) -> list[int]:
        self._raise()
        return []

    def mark_l0_distilled(self, event_ids: list[int], **kwargs: Any) -> None:
        self._raise()


def open_postgres_store(dsn: str, *, schema: str = "daily_run") -> DailyRunStore:
    return PostgresDailyRunStore(dsn, schema=schema)
