# -*- coding: utf-8
"""Block dev/test writes against the canonical prod daily_run.db."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.storage.config import (
    sqlite_db_path,
    storage_enabled,
    storage_settings,
)


def canonical_prod_sqlite_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "daily_run.db"


def canonical_daily_run_data_root() -> Path:
    return Path.home() / ".agent-reach" / "daily_run"


def is_canonical_daily_run_data_root() -> bool:
    # Resolve via config module so pytest monkeypatches on daily_run_data_root apply.
    from agent_reach.daily_run.storage.config import daily_run_data_root as _daily_run_data_root

    try:
        return _daily_run_data_root().resolve() == canonical_daily_run_data_root().resolve()
    except OSError:
        return str(_daily_run_data_root()) == str(canonical_daily_run_data_root())


def is_prod_sqlite_path(path: Path | str) -> bool:
    try:
        return Path(path).expanduser().resolve() == canonical_prod_sqlite_path().resolve()
    except OSError:
        return str(Path(path).expanduser()) == str(canonical_prod_sqlite_path())


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_synthetic_test_payload(kind: str, payload: Any) -> bool:
    """Detect obvious unit-test / manual probe payloads."""
    if not isinstance(payload, dict):
        return False

    kind_norm = str(kind or "").strip().lower()

    if kind_norm == "portfolio":
        return str(payload.get("source") or "").strip().lower() == "test"

    if kind_norm == "harness_refinement":
        return str(payload.get("evidence") or "").strip().lower() == "test"

    trade_like = payload
    if kind_norm == "trade_case":
        nested = payload.get("record")
        if isinstance(nested, dict):
            trade_like = nested

    if kind_norm in ("trade", "trade_case", "trade_action", "trade_batch"):
        reasoning = str(trade_like.get("reasoning") or "").strip().lower()
        if reasoning == "test":
            return True
        for action in trade_like.get("actions") or []:
            if not isinstance(action, dict):
                continue
            if str(action.get("reasoning") or "").strip().lower() == "test":
                return True
    return False


def storage_write_blocked_reason(
    settings: Optional[dict[str, Any]] = None,
    *,
    kind: str = "",
    payload: Any = None,
    source: str = "",
) -> Optional[str]:
    """Return a short reason when a storage write must be skipped."""
    if not storage_enabled(settings):
        return "storage_disabled"

    cfg = storage_settings(settings)
    if cfg.get("allow_prod_writes") is False:
        db_path = sqlite_db_path(settings)
        if is_prod_sqlite_path(db_path):
            return "allow_prod_writes_disabled"

    db_path = sqlite_db_path(settings)
    if not is_prod_sqlite_path(db_path):
        return None

    if _truthy_env("AGENT_REACH_STORAGE_ALLOW_PROD"):
        return None

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest_must_not_write_canonical_prod_db"

    guard_synthetic = cfg.get("block_synthetic_on_prod", True) is not False
    probe = dict(payload) if isinstance(payload, dict) else {}
    if source:
        probe.setdefault("source", source)
    if guard_synthetic and is_synthetic_test_payload(kind, probe):
        return "synthetic_test_payload"

    return None


def storage_write_allowed(
    settings: Optional[dict[str, Any]] = None,
    *,
    kind: str = "",
    payload: Any = None,
    source: str = "",
) -> bool:
    reason = storage_write_blocked_reason(
        settings,
        kind=kind,
        payload=payload,
        source=source,
    )
    return reason in (None, "storage_disabled")


def storage_db_reads_blocked_reason(
    settings: Optional[dict[str, Any]] = None,
    *,
    file_path: Optional[Path] = None,
    explicit_path: bool = False,
) -> Optional[str]:
    """Block pytest from read-through on the canonical prod SQLite DB."""
    if explicit_path:
        return None
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if _truthy_env("AGENT_REACH_STORAGE_ALLOW_PROD"):
        return None
    if not storage_enabled(settings):
        return None
    if not is_canonical_daily_run_data_root():
        return None
    if is_prod_sqlite_path(sqlite_db_path(settings)):
        return "pytest_must_not_read_canonical_prod_db"
    return None
