# -*- coding: utf-8
"""Multi-source A-share quote fetch with retry and coverage tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.retry_utils import retry_with_backoff


def normalize_code(code: str) -> str:
    text = str(code).strip()
    if text.isdigit():
        return text.zfill(6)[-6:]
    return text


def code_to_xueqiu_symbol(code: str) -> str:
    text = code.strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            return text
    text = text.zfill(6)
    if text.startswith(("5", "6", "9")):
        return f"SH{text}"
    if text.startswith(("4", "8")):
        return f"BJ{text}"
    return f"SZ{text}"


@dataclass
class QuoteFetchResult:
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return 0.0

    def coverage_for(self, codes: list[str]) -> float:
        if not codes:
            return 1.0
        unique = list(dict.fromkeys(normalize_code(c) for c in codes if c))
        if not unique:
            return 1.0
        hit = sum(1 for c in unique if c in self.quotes)
        return hit / len(unique)


def _fetch_xueqiu(codes: list[str], *, max_retries: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def _load_channel():
        from agent_reach.channels import xueqiu as xq_mod

        xq_mod._ensure_cookies()
        return xq_mod.XueqiuChannel()

    channel = retry_with_backoff(_load_channel, max_retries=max_retries, label="xueqiu_channel")
    for code in codes:
        try:
            q = retry_with_backoff(
                lambda c=code: channel.get_stock_quote(code_to_xueqiu_symbol(c)),
                max_retries=max_retries,
                label=f"xueqiu_{code}",
            )
            price = q.get("current")
            if price is None:
                continue
            out[code] = {
                "code": code,
                "name": q.get("name", code),
                "price": float(price),
                "change_pct": float(q.get("percent") or 0),
                "reference_price": float(q.get("last_close") or price),
                "source": "xueqiu",
            }
        except Exception:
            continue
    return out


def _fetch_akshare(codes: list[str], *, max_retries: int, ttl: int) -> dict[str, dict[str, Any]]:
    from agent_reach.daily_run.akshare_adapter import fetch_quotes_batch

    return retry_with_backoff(
        lambda: fetch_quotes_batch(codes, ttl=ttl),
        max_retries=max_retries,
        label="akshare_batch",
    )


def fetch_quotes_map(
    codes: list[str],
    config=None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> QuoteFetchResult:
    """Fetch quotes using configured source priority with retry."""
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    qcfg = cfg.get("quote_fetch") or {}
    order = qcfg.get("sources") or ["xueqiu", "akshare"]
    max_retries = int(qcfg.get("max_retries", 2))
    ttl = int((cfg.get("akshare") or {}).get("spot_ttl", 60))

    unique = list(dict.fromkeys(normalize_code(c) for c in codes if c))
    result = QuoteFetchResult()
    missing = list(unique)

    fetchers = {
        "xueqiu": lambda cs: _fetch_xueqiu(cs, max_retries=max_retries),
        "akshare": lambda cs: _fetch_akshare(cs, max_retries=max_retries, ttl=ttl),
    }

    for source in order:
        if not missing:
            break
        fn = fetchers.get(source)
        if fn is None:
            continue
        try:
            batch = fn(missing)
        except Exception as exc:
            for code in missing:
                result.errors.setdefault(code, f"{source}: {exc}")
            continue
        if batch:
            result.sources_used.append(source)
        for code in list(missing):
            if code in batch:
                result.quotes[code] = batch[code]
                missing.remove(code)
                result.errors.pop(code, None)

    for code in missing:
        result.errors.setdefault(code, "no quote from configured sources")
    return result
