# -*- coding: utf-8
"""06:55 CST quote probe — WARN-only pre-open D1 smoke on holdings/watchlist codes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.ops_trading_day_precheck import CheckResult
from agent_reach.daily_run.quote_fetch import QuoteFetchResult, fetch_quotes_map, normalize_code
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai


@dataclass
class QuoteProbeOutcome:
    codes: list[str]
    fetch: QuoteFetchResult
    per_code: dict[str, str]  # code -> ok | missing | stale
    coverage_pct: float
    manifest_path: Optional[Path]


def _quote_probe_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    raw = (settings.get("ops") or {}).get("quote_probe") or {}
    max_codes = int(raw.get("max_codes", 12))
    if max_codes < 1:
        max_codes = 12
    return {
        "enabled": raw.get("enabled") is not False,
        "max_codes": max_codes,
        "include_holdings": raw.get("include_holdings") is not False,
        "include_watchlist": raw.get("include_watchlist") is not False,
        "push_warn": raw.get("push_warn") is not False,
        "extra_codes": [
            normalize_code(str(c))
            for c in (raw.get("extra_codes") or [])
            if c and normalize_code(str(c))
        ],
    }


def select_probe_codes(
    portfolio: dict[str, Any],
    settings: dict[str, Any],
) -> list[str]:
    """Small deduped set: holdings → watchlist → primary → extra_codes (capped)."""
    cfg = _quote_probe_cfg(settings)
    limit = cfg["max_codes"]
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        c = normalize_code(code)
        if not c or c in seen:
            return
        seen.add(c)
        ordered.append(c)

    if cfg["include_holdings"]:
        for row in portfolio.get("holdings") or []:
            shares = row.get("shares") or row.get("quantity") or 0
            try:
                qty = float(shares)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            _add(str(row.get("code") or ""))
            if len(ordered) >= limit:
                return ordered[:limit]

    if cfg["include_watchlist"]:
        for row in portfolio.get("watchlist") or []:
            _add(str(row.get("code") or ""))
            if len(ordered) >= limit:
                return ordered[:limit]

    primary = normalize_code(str(portfolio.get("primary_code") or ""))
    if primary:
        _add(primary)

    for code in cfg["extra_codes"]:
        _add(code)
        if len(ordered) >= limit:
            break

    return ordered[:limit]


def _classify_quote(code: str, fetch: QuoteFetchResult) -> str:
    if code in fetch.errors and code not in fetch.quotes:
        return "missing"
    row = fetch.quotes.get(code)
    if not row:
        return "missing"
    price = row.get("price")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    if price_f is None or price_f <= 0:
        return "missing"
    ref = row.get("reference_price") or row.get("prev_close")
    try:
        ref_f = float(ref) if ref is not None else None
    except (TypeError, ValueError):
        ref_f = None
    change = row.get("change_pct")
    try:
        change_f = float(change) if change is not None else 0.0
    except (TypeError, ValueError):
        change_f = 0.0
    vol = row.get("volume")
    try:
        vol_f = float(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_f = None
    if (
        ref_f is not None
        and abs(price_f - ref_f) < 1e-9
        and abs(change_f) < 1e-9
        and vol_f is not None
        and vol_f <= 0
    ):
        return "stale"
    return "ok"


def _save_probe_manifest(
    payload: dict[str, Any],
) -> Path:
    from agent_reach.daily_run.run_manifest import save_run_manifest

    return save_run_manifest("quote_probe", payload, duration_ms=payload.get("duration_ms"))


def run_quote_probe(
    *,
    settings: Optional[dict[str, Any]] = None,
    skip_non_trading: bool = True,
    portfolio: Optional[dict[str, Any]] = None,
) -> tuple[list[CheckResult], QuoteProbeOutcome, int]:
    """Always exit 0 from caller unless disabled skip; issues are WARN severity only."""
    settings = settings or load_settings()
    cfg = _quote_probe_cfg(settings)
    today = today_shanghai()
    trading, reason = is_trading_day(today, settings=settings)

    results: list[CheckResult] = [
        CheckResult(
            "calendar",
            True,
            f"{today.isoformat()} {'交易日' if trading else '非交易日'} ({reason})",
            severity="info",
        )
    ]

    empty_outcome = QuoteProbeOutcome([], QuoteFetchResult(), {}, 1.0, None)

    if not cfg["enabled"]:
        results.append(
            CheckResult(
                "quote_probe",
                True,
                "已跳过 (ops.quote_probe.enabled=false)",
                severity="info",
            )
        )
        return results, empty_outcome, 0

    if skip_non_trading and not trading:
        results.append(
            CheckResult(
                "quote_probe",
                True,
                "非交易日跳过报价探针",
                severity="info",
            )
        )
        return results, empty_outcome, 0

    if portfolio is None:
        from agent_reach.daily_run.snapshot_builder import load_portfolio

        try:
            portfolio = load_portfolio(settings=settings)
        except FileNotFoundError as exc:
            results.append(
                CheckResult(
                    "quote_probe",
                    True,
                    f"跳过：{exc}",
                    severity="warn",
                )
            )
            return results, empty_outcome, 0

    codes = select_probe_codes(portfolio, settings)
    if not codes:
        results.append(
            CheckResult(
                "quote_probe",
                True,
                "无持仓/观察池代码可探针",
                severity="info",
            )
        )
        return results, empty_outcome, 0

    fetch = fetch_quotes_map(codes, settings=settings)
    per_code = {c: _classify_quote(c, fetch) for c in codes}
    coverage = fetch.coverage_for(codes)
    bad = [c for c, st in per_code.items() if st != "ok"]
    missing = [c for c in bad if per_code[c] == "missing"]
    stale = [c for c in bad if per_code[c] == "stale"]

    sources = ",".join(fetch.sources_used) or "none"
    detail_parts = [
        f"{len(codes)} codes",
        f"coverage {coverage * 100:.0f}%",
        f"sources={sources}",
    ]
    if bad:
        detail_parts.append(f"missing={','.join(missing) or '-'}")
        detail_parts.append(f"stale={','.join(stale) or '-'}")
    detail = "; ".join(detail_parts)

    if bad:
        results.append(
            CheckResult("quote_probe", True, detail, severity="warn"),
        )
    else:
        results.append(CheckResult("quote_probe", True, detail, severity="info"))

    manifest_payload = {
        "codes": codes,
        "coverage_pct": round(coverage * 100, 2),
        "sources_used": list(fetch.sources_used),
        "per_code": per_code,
        "errors": dict(fetch.errors),
        "quotes_preview": {
            c: {
                k: fetch.quotes[c].get(k)
                for k in ("price", "change_pct", "source", "volume")
                if c in fetch.quotes
            }
            for c in codes
        },
    }
    manifest_path: Optional[Path] = None
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("OPS_QUOTE_PROBE_SKIP_MANIFEST"):
        pass
    else:
        try:
            manifest_path = _save_probe_manifest(manifest_payload)
        except OSError:
            manifest_path = None

    outcome = QuoteProbeOutcome(
        codes=codes,
        fetch=fetch,
        per_code=per_code,
        coverage_pct=coverage,
        manifest_path=manifest_path,
    )
    return results, outcome, 0


def format_quote_probe_summary(results: list[CheckResult]) -> str:
    lines = ["=== ops-quote-probe (06:55) ==="]
    for r in results:
        if r.ok:
            mark = "OK" if r.severity == "fail" else r.severity.upper()
        else:
            mark = "FAIL"
        lines.append(f"[{mark}] {r.name}: {r.detail}")
    lines.append("--- PASS (exit 0; quote issues are WARN only) ---")
    return "\n".join(lines)


def notify_quote_probe_warn(
    summary: str,
    *,
    settings: dict[str, Any],
    config=None,
) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.job_health import feishu_ops_notify_enabled

    if not feishu_ops_notify_enabled(settings, config):
        return {"skipped": True, "reason": "feishu_unconfigured_or_disabled"}

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg = config or Config()
    title = "⚠️ ops 报价探针 WARN"
    body = summary + "\n\n（自动推送 · ops-quote-probe · 不阻塞早盘）"
    try:
        return send_card(cfg, title, body, template="yellow")
    except FeishuError:
        return {"skipped": True, "reason": "feishu_error"}


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="06:55 CST quote probe (WARN only)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--force-non-trading",
        action="store_true",
        help="Run even on non-trading days",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    results, outcome, exit_code = run_quote_probe(
        settings=settings,
        skip_non_trading=not args.force_non_trading,
    )
    summary = format_quote_probe_summary(results)

    has_warn = any(r.severity == "warn" for r in results)
    if has_warn and _quote_probe_cfg(settings)["push_warn"]:
        notify_quote_probe_warn(summary, settings=settings)

    if args.json:
        payload = {
            "exit_code": exit_code,
            "checks": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "detail": r.detail,
                    "severity": r.severity,
                }
                for r in results
            ],
            "quote_probe": {
                "codes": outcome.codes,
                "coverage_pct": outcome.coverage_pct,
                "per_code": outcome.per_code,
                "manifest_path": str(outcome.manifest_path) if outcome.manifest_path else None,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(summary)
        if outcome.manifest_path:
            print(f"manifest: {outcome.manifest_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())