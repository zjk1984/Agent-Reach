# -*- coding: utf-8
"""Storage backend protocol for daily-run persistence."""

from __future__ import annotations

from typing import Any, Optional, Protocol


class DailyRunStore(Protocol):
    def status(self) -> dict[str, Any]: ...

    def append_l0_event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        at: str = "",
        source_path: str = "",
        dedupe_key: str = "",
    ) -> int: ...

    def upsert_portfolio(
        self,
        portfolio: dict[str, Any],
        *,
        source: str = "save",
        at: str = "",
    ) -> int: ...

    def sync_harness_state(self, state_payload: dict[str, Any], *, at: str = "") -> None: ...

    def append_harness_entry_history(
        self,
        *,
        kind: str,
        entry_id: str,
        action: str,
        payload: dict[str, Any],
        at: str = "",
    ) -> None: ...

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
    ) -> int: ...

    def get_l0_event(self, event_id: int) -> Optional[dict[str, Any]]: ...

    def query_l0_events(
        self,
        *,
        kind: str = "",
        since: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def query_l1_atoms(
        self,
        *,
        kind: str = "",
        code: str = "",
        since: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def query_trades(
        self,
        *,
        code: str = "",
        since: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def list_undistilled_l0_event_ids(self, *, limit: int = 500) -> list[int]: ...

    def mark_l0_distilled(self, event_ids: list[int], *, job: str = "distill") -> None: ...
