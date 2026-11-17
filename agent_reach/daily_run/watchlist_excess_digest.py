# -*- coding: utf-8
"""Saturday watchlist paper P&L — T+3/T+5 vs CSI300 from manifest add events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import is_trading_day, trading_day_after, trading_day_before
from agent_reach.daily_run.weekly_card_metrics import fetch_benchmark_period_return

PriceResolver = Callable[[str, date], Optional[float]]


_DEFAULT_CFG: dict[str, Any] = {
    "enabled": False,
    "lookback_trading_days": 30,
    "horizons": [3, 5],
    "include_hold_period": True,
    "quote_fallback": False,
    "table_limit": 12,
}


def watchlist_excess_digest_cfg(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    wl = (settings or {}).get("watchlist") or {}
    raw = wl.get("excess_digest") or {}
    merged = dict(_DEFAULT_CFG)
    merged.update(raw)
    horizons = merged.get("horizons") or [3, 5]
    merged["horizons"] = [int(h) for h in horizons if int(h) > 0]
    return merged


def watchlist_excess_digest_enabled(settings: Optional[dict[str, Any]]) -> bool:
    return bool(watchlist_excess_digest_cfg(settings).get("enabled"))


def _manifest_day(record: dict[str, Any]) -> str:
    return str(record.get("_run_date") or record.get("date") or "")[:10]


def _watchlist_changes_from_manifest(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    changes: list[dict[str, Any]] = []
    for root in (payload, payload.get("result") or {}):
        if not isinstance(root, dict):
            continue
        for key in ("watchlist_adjust",):
            block = root.get(key)
            if isinstance(block, dict):
                changes.extend(block.get("changes") or [])
        summary = root.get("watchlist_adjust_summary")
        if isinstance(summary, dict):
            changes.extend(summary.get("changes") or [])
    return [c for c in changes if isinstance(c, dict)]


def collect_watchlist_add_events(
    manifests: list[dict[str, Any]],
    *,
    window_start: date,
    window_end: date,
) -> list[dict[str, Any]]:
    """Deduped watchlist ``add`` rows from run manifests in [window_start, window_end]."""
    ws, we = window_start.isoformat(), window_end.isoformat()
    seen: set[tuple[str, str]] = set()
    events: list[dict[str, Any]] = []
    for record in manifests:
        day = _manifest_day(record)
        if not day or day < ws or day > we:
            continue
        for ch in _watchlist_changes_from_manifest(record):
            if str(ch.get("action") or "").lower() != "add":
                continue
            code = _normalize_code(str(ch.get("code") or ""))
            if not code:
                continue
            key = (day, code)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "added_date": day,
                    "code": code,
                    "name": str(ch.get("name") or code),
                    "reason": str(ch.get("reason") or ""),
                    "phase": str(record.get("job") or ""),
                }
            )
    events.sort(key=lambda e: (e["added_date"], e["code"]))
    return events


def _iter_manifest_snapshots(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    snaps: list[dict[str, Any]] = []
    if isinstance(payload.get("result"), dict):
        snap = (payload["result"] or {}).get("snapshot")
        if isinstance(snap, dict):
            snaps.append(snap)
    for sr in payload.get("symbol_results") or []:
        if not isinstance(sr, dict):
            continue
        snap = (sr.get("result") or {}).get("snapshot")
        if isinstance(snap, dict):
            row = dict(snap)
            row.setdefault("code", sr.get("code"))
            snaps.append(row)
    if isinstance(payload.get("snapshot"), dict):
        snaps.append(dict(payload["snapshot"]))
    return snaps


def _price_from_snapshot_row(code: str, snap: dict[str, Any]) -> Optional[float]:
    snap_code = _normalize_code(str(snap.get("code") or ""))
    if snap_code == code:
        px = snap.get("price")
        if px is not None:
            return float(px)
    for w in snap.get("watchlist") or []:
        if not isinstance(w, dict):
            continue
        if _normalize_code(str(w.get("code") or "")) == code and w.get("price") is not None:
            return float(w["price"])
    for h in (snap.get("portfolio") or {}).get("watchlist") or []:
        if not isinstance(h, dict):
            continue
        if _normalize_code(str(h.get("code") or "")) == code and h.get("price") is not None:
            return float(h["price"])
    return None


def symbol_close_from_manifests(
    code: str,
    day: date,
    manifests: list[dict[str, Any]],
) -> Optional[float]:
    ds = day.isoformat()
    day_records = [m for m in manifests if _manifest_day(m) == ds]
    # Prefer close job, then morning, then any.
    for job_pref in ("close", "morning", "midday", "intraday"):
        for record in day_records:
            if str(record.get("job") or "") != job_pref:
                continue
            for snap in _iter_manifest_snapshots(record):
                px = _price_from_snapshot_row(code, snap)
                if px is not None:
                    return px
    for record in day_records:
        for snap in _iter_manifest_snapshots(record):
            px = _price_from_snapshot_row(code, snap)
            if px is not None:
                return px
    return None


def _return_pct(entry_px: float, exit_px: float) -> float:
    if entry_px <= 0:
        return 0.0
    return round((exit_px - entry_px) / entry_px * 100.0, 2)


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _horizon_summary(rows: list[dict[str, Any]], horizon: int, field_prefix: str) -> dict[str, Any]:
    matured = [r for r in rows if r.get(f"{field_prefix}_status") == "matured"]
    stock_rets = [float(r[f"{field_prefix}_stock_pct"]) for r in matured if r.get(f"{field_prefix}_stock_pct") is not None]
    bench_rets = [float(r[f"{field_prefix}_bench_pct"]) for r in matured if r.get(f"{field_prefix}_bench_pct") is not None]
    excess_vals = [float(r[f"{field_prefix}_excess_pct"]) for r in matured if r.get(f"{field_prefix}_excess_pct") is not None]
    wins = sum(1 for x in excess_vals if x > 0)
    return {
        "horizon": horizon,
        "matured": len(matured),
        "pending": sum(1 for r in rows if r.get(f"{field_prefix}_status") == "pending"),
        "insufficient": sum(1 for r in rows if r.get(f"{field_prefix}_status") == "insufficient_data"),
        "avg_stock_pct": _mean(stock_rets),
        "avg_bench_pct": _mean(bench_rets),
        "avg_excess_pct": _mean(excess_vals),
        "win_rate_pct": round(wins / len(excess_vals) * 100, 1) if excess_vals else None,
    }


@dataclass
class WatchlistExcessDigest:
    enabled: bool
    as_of: str
    window_start: str
    window_end: str
    benchmark_name: str
    events: list[dict[str, Any]] = field(default_factory=list)
    horizons: list[dict[str, Any]] = field(default_factory=list)
    hold_period: Optional[dict[str, Any]] = None
    message: str = ""
    table_limit: int = 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "as_of": self.as_of,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "benchmark_name": self.benchmark_name,
            "events": self.events,
            "horizons": self.horizons,
            "hold_period": self.hold_period,
            "message": self.message,
            "table_limit": self.table_limit,
        }


def build_watchlist_excess_digest(
    *,
    manifests: list[dict[str, Any]],
    as_of: date,
    settings: Optional[dict[str, Any]] = None,
    price_resolver: Optional[PriceResolver] = None,
    current_watchlist_codes: Optional[set[str]] = None,
) -> WatchlistExcessDigest:
    cfg = watchlist_excess_digest_cfg(settings)
    enabled = bool(cfg.get("enabled"))
    lookback = max(1, int(cfg.get("lookback_trading_days") or 30))
    window_end = as_of
    window_start = trading_day_before(window_end, lookback, settings=settings)
    bench_name = str(((settings or {}).get("weekly_report") or {}).get("benchmark_index_name") or "沪深300")

    if not enabled:
        return WatchlistExcessDigest(
            enabled=False,
            as_of=as_of.isoformat(),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            benchmark_name=bench_name,
            message="watchlist.excess_digest 未启用",
        )

    def resolve_px(code: str, day: date) -> Optional[float]:
        if price_resolver is not None:
            px = price_resolver(code, day)
            if px is not None:
                return px
        return symbol_close_from_manifests(code, day, manifests)

    events_raw = collect_watchlist_add_events(
        manifests,
        window_start=window_start,
        window_end=window_end,
    )
    if not events_raw:
        return WatchlistExcessDigest(
            enabled=True,
            as_of=as_of.isoformat(),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            benchmark_name=bench_name,
            message="观察窗口内无纳入记录",
        )

    horizons = [int(h) for h in (cfg.get("horizons") or [3, 5])]
    rows: list[dict[str, Any]] = []
    held_codes = current_watchlist_codes or set()

    for ev in events_raw:
        added = date.fromisoformat(ev["added_date"])
        entry_px = resolve_px(ev["code"], added)
        row: dict[str, Any] = dict(ev)
        row["entry_price"] = entry_px
        for h in horizons:
            prefix = f"t{h}"
            exit_day = trading_day_after(added, h, settings=settings)
            if exit_day > window_end:
                row[f"{prefix}_status"] = "pending"
                continue
            exit_px = resolve_px(ev["code"], exit_day)
            if entry_px is None or exit_px is None:
                row[f"{prefix}_status"] = "insufficient_data"
                continue
            stock_pct = _return_pct(entry_px, exit_px)
            bench = fetch_benchmark_period_return(added, exit_day, settings=settings)
            bench_pct = bench.get("return_pct")
            excess = (
                round(stock_pct - float(bench_pct), 2)
                if bench_pct is not None
                else None
            )
            row[f"{prefix}_status"] = "matured"
            row[f"{prefix}_exit_date"] = exit_day.isoformat()
            row[f"{prefix}_stock_pct"] = stock_pct
            row[f"{prefix}_bench_pct"] = bench_pct
            row[f"{prefix}_excess_pct"] = excess
        if cfg.get("include_hold_period") and ev["code"] in held_codes and entry_px is not None:
            ok, _ = is_trading_day(window_end, settings=settings)
            hold_end = window_end if ok else trading_day_before(window_end, 0, settings=settings)
            hold_px = resolve_px(ev["code"], hold_end)
            if hold_px is not None:
                stock_pct = _return_pct(entry_px, hold_px)
                bench = fetch_benchmark_period_return(added, hold_end, settings=settings)
                bench_pct = bench.get("return_pct")
                row["hold_stock_pct"] = stock_pct
                row["hold_bench_pct"] = bench_pct
                row["hold_excess_pct"] = (
                    round(stock_pct - float(bench_pct), 2) if bench_pct is not None else None
                )
        rows.append(row)

    horizon_summaries = [_horizon_summary(rows, h, f"t{h}") for h in horizons]
    hold_summary: Optional[dict[str, Any]] = None
    if cfg.get("include_hold_period"):
        hold_stock = [float(r["hold_stock_pct"]) for r in rows if r.get("hold_stock_pct") is not None]
        hold_excess = [float(r["hold_excess_pct"]) for r in rows if r.get("hold_excess_pct") is not None]
        if hold_stock:
            hold_summary = {
                "count": len(hold_stock),
                "avg_stock_pct": _mean(hold_stock),
                "avg_excess_pct": _mean(hold_excess),
            }

    msg_parts = [f"纳入 {len(rows)} 笔"]
    for hs in horizon_summaries:
        msg_parts.append(f"T+{hs['horizon']}可评 {hs['matured']}")
    return WatchlistExcessDigest(
        enabled=True,
        as_of=as_of.isoformat(),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        benchmark_name=bench_name,
        events=rows,
        horizons=horizon_summaries,
        hold_period=hold_summary,
        message=" · ".join(msg_parts),
        table_limit=int(cfg.get("table_limit") or 12),
    )


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "+" if float(v) > 0 else ""
    return f"{sign}{float(v):.2f}%"


def render_watchlist_excess_markdown(
    digest: WatchlistExcessDigest | dict[str, Any],
    *,
    table_limit: int = 12,
) -> str:
    data = digest.to_dict() if isinstance(digest, WatchlistExcessDigest) else dict(digest)
    if not data.get("enabled"):
        return ""
    lines = [
        "## 观察池 T+3/T+5 超额（paper）",
        f"- 窗口：**{data.get('window_start')}** ~ **{data.get('window_end')}**",
        f"- {data.get('message') or '—'}",
    ]
    for hs in data.get("horizons") or []:
        h = int(hs.get("horizon") or 0)
        avg_ex = hs.get("avg_excess_pct")
        lines.append(
            f"- **T+{h} 均值**：个股 {_fmt_pct(hs.get('avg_stock_pct'))} · "
            f"{data.get('benchmark_name')} {_fmt_pct(hs.get('avg_bench_pct'))} · "
            f"超额 {_fmt_pct(avg_ex)}"
            + (
                f"（胜率 {hs.get('win_rate_pct'):.0f}%）"
                if hs.get("win_rate_pct") is not None
                else ""
            )
        )
    hold = data.get("hold_period") or {}
    if hold.get("count"):
        lines.append(
            f"- **持仓期（仍在观察池）**：{hold['count']} 只 · "
            f"均值 {_fmt_pct(hold.get('avg_stock_pct'))} · "
            f"超额 {_fmt_pct(hold.get('avg_excess_pct'))}"
        )

    events = data.get("events") or []
    if events:
        lines.extend(["", "| 纳入日 | 标的 | 原因 | T+3超额 | T+5超额 |", "|---|---|---|---:|---:|"])
        for row in events[: max(1, table_limit)]:
            reason = (row.get("reason") or "")[:24]
            t3 = _fmt_pct(row.get("t3_excess_pct")) if row.get("t3_status") == "matured" else "待"
            t5 = _fmt_pct(row.get("t5_excess_pct")) if row.get("t5_status") == "matured" else "待"
            name = row.get("name") or row.get("code")
            lines.append(
                f"| {row.get('added_date')} | {name}({row.get('code')}) | {reason} | {t3} | {t5} |"
            )
    lines.append("")
    return "\n".join(lines)


def watchlist_excess_feishu_lines(digest: WatchlistExcessDigest | dict[str, Any]) -> list[str]:
    """Compact lines for quant-digest Feishu card (weekly_card_metrics-style)."""
    data = digest.to_dict() if isinstance(digest, WatchlistExcessDigest) else dict(digest)
    if not data.get("enabled") or not data.get("events"):
        return []
    bits = [f"**观察池 paper** {data.get('message') or ''}"]
    for hs in data.get("horizons") or []:
        h = int(hs.get("horizon") or 0)
        if hs.get("matured"):
            bits.append(
                f"T+{h} 超额均值 {_fmt_pct(hs.get('avg_excess_pct'))}（{hs['matured']}笔）"
            )
    return bits