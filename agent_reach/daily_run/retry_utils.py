# -*- coding: utf-8
"""Bounded retry helpers (Vibe-Trading retry_with_budget pattern)."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    backoff: tuple[float, ...] = (1.0, 2.0, 4.0),
    transient: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
) -> T:
    """Call *fn* with exponential backoff on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except transient as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = backoff[min(attempt, len(backoff) - 1)]
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
