# -*- coding: utf-8
"""Weekly quant PM digest — PnL, trades, job health, harness playbook delta."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import is_trading_day
from agent_reach.daily_run.weekly_report import (
    _compute_realized_pnl,
    _load_trade_ledger_range,
    compute_weekly_nav_pnl_from_manifests,
    trading_week_range,
)

TRACKED_SCHEDULE_JOBS = ("morning", "midday", "intraday", "close")


def last_n_trading_days(
    end: date,
    n: int,
    *,
    settings: Optional[dict[str, Any]] = None,
    max_scan: int = 90,
) -> list[date]:
    """Return the ``n`` most recent trading days on or before ``end`` (oldest first)."""
    if n <= 0:
        return []
    out: list[date] = []
    cursor = end
    scanned = 0
    while len(out) < n and scanned < max_scan:
        ok, _ = is_trading_day(cursor, settings=settings)
        if ok:
            out.append(cursor)
        cursor -= timedelta(days=1)
        scanned += 1
    out.reverse()
    return out


def summarize_pnl_rows(
    rows: list[Any],
    *,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    """Aggregate daily PnL history rows for the trading week."""
    ws, we = week_start.isoformat(), week_end.isoformat()
    daily: list[dict[str, Any]] = []
    weekly_pnl = 0.0
    has_pct = False
    pct_sum = 0.0
    end_total: Optional[float] = None
    cumulative: Optional[float] = None

    for row in rows:
        if hasattr(row, "to_dict"):
            rec = row.to_dict()
        else:
            rec = dict(row)
        day = str(rec.get("date") or "")[:10]
        if not day or day < ws or day > we:
            continue
        pnl = float(rec.get("daily_pnl") or 0)
        weekly_pnl += pnl
        pct = rec.get("daily_pnl_pct")
        if pct is not None:
            has_pct = True
            pct_sum += float(pct)
        if rec.get("end_total") is not None:
            end_total = float(rec["end_total"])
        if rec.get("cumulative_pnl") is not None:
            cumulative = float(rec["cumulative_pnl"])
        daily.append(
            {
                "date": day,
                "daily_pnl": round(pnl, 2),
                "daily_pnl_pct": pct,
                "end_total": rec.get("end_total"),
            }
        )

    daily.sort(key=lambda x: x["date"])
    start_total: Optional[float] = None
    if daily and daily[0].get("end_total") is not None and daily[0].get("daily_pnl") is not None:
        start_total = float(daily[0]["end_total"]) - float(daily[0]["daily_pnl"])

    weekly_pnl_pct: Optional[float] = None
    if start_total and start_total > 0 and daily:
        weekly_pnl_pct = round(weekly_pnl / start_total * 100, 2)
    elif has_pct:
        weekly_pnl_pct = round(pct_sum, 2)

    return {
        "week_start": ws,
        "week_end": we,
        "weekly_pnl": round(weekly_pnl, 2),
        "weekly_pnl_pct": weekly_pnl_pct,
        "end_total": end_total,
        "cumulative_pnl": cumulative,
        "daily": daily,
        "trading_days_with_pnl": len(daily),
    }


def _iter_ledger_actions(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in trades:
        actions = entry.get("actions")
        if isinstance(actions, list) and actions:
            day = str(entry.get("date") or entry.get("at") or "")[:10]
            for act in actions:
                if isinstance(act, dict):
                    row = dict(act)
                    if day and not row.get("date"):
                        row["date"] = day
                    out.append(row)
            continue
        if isinstance(entry, dict) and entry.get("side"):
            out.append(entry)
    return out


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact trade ledger stats for the digest."""
    actions = _iter_ledger_actions(trades)
    buys = sum(1 for t in actions if str(t.get("side") or "").lower() == "buy")
    sells = sum(1 for t in actions if str(t.get("side") or "").lower() == "sell")
    realized = round(_compute_realized_pnl(trades), 2)
    highlights: list[str] = []
    for t in actions[-8:]:
        side = str(t.get("side") or "?")
        code = t.get("code") or ""
        name = t.get("name") or code
        shares = t.get("shares") or ""
        highlights.append(f"{str(t.get('date') or '')[:10]} {side} {name}({code}) ×{shares}")
    return {
        "trade_count": len(trades),
        "buys": buys,
        "sells": sells,
        "realized_pnl": realized,
        "highlights": highlights,
    }


def manifest_jobs_by_day(manifests: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for rec in manifests:
        day = str(rec.get("_run_date") or rec.get("date") or "")[:10]
        job = str(rec.get("job") or "")
        if day and job:
            out.setdefault(day, set()).add(job)
    return out


def summarize_job_health_snapshot(job_health: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = (job_health or {}).get("jobs") or {}
    rows: list[dict[str, Any]] = []
    for name in sorted(jobs.keys()):
        entry = jobs[name] or {}
        rows.append(
            {
                "job": name,
                "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                "last_success_at": entry.get("last_success_at"),
                "last_error": entry.get("last_error"),
            }
        )
    return rows


def summarize_recent_job_coverage(
    trading_days: list[date],
    manifests_by_day: dict[str, set[str]],
    *,
    tracked_jobs: tuple[str, ...] = TRACKED_SCHEDULE_JOBS,
) -> list[dict[str, Any]]:
    """Per-day manifest presence for core cron jobs (proxy for recent ops health)."""
    rows: list[dict[str, Any]] = []
    for d in trading_days:
        ds = d.isoformat()
        present = manifests_by_day.get(ds) or set()
        missing = [j for j in tracked_jobs if j not in present]
        rows.append(
            {
                "date": ds,
                "present": sorted(present & set(tracked_jobs)),
                "missing": missing,
                "ok": not missing,
            }
        )
    return rows


def playbook_delta_from_refinements(
    refinements: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> list[dict[str, Any]]:
    ws, we = week_start.isoformat(), week_end.isoformat()
    out: list[dict[str, Any]] = []
    for raw in refinements:
        if not isinstance(raw, dict):
            continue
        created = str(raw.get("created_at") or "")[:10]
        if not created or created < ws or created > we:
            continue
        edits = [e for e in (raw.get("edits") or []) if str(e.get("kind") or "") == "playbook"]
        changes = [
            str(c)
            for c in (raw.get("changes") or [])
            if "playbook" in str(c).lower()
        ]
        if not edits and not changes:
            continue
        lines: list[str] = []
        for ch in (raw.get("changes") or [])[:6]:
            lines.append(str(ch))
        for ed in edits[:4]:
            action = ed.get("action") or "edit"
            eid = ed.get("entry_id") or ""
            lines.append(f"{action} playbook/{eid}")
        out.append(
            {
                "id": raw.get("id") or "",
                "job": raw.get("job") or "",
                "trigger": raw.get("trigger") or "",
                "created_at": raw.get("created_at") or created,
                "lines": lines[:8],
            }
        )
    return out


def playbook_entries_touched_in_week(
    playbook_entries: dict[str, Any],
    *,
    week_start: date,
    week_end: date,
) -> list[dict[str, Any]]:
    ws, we = week_start.isoformat(), week_end.isoformat()
    touched: list[dict[str, Any]] = []
    for entry_id, raw in (playbook_entries or {}).items():
        if not isinstance(raw, dict):
            continue
        updated = str(raw.get("updated_at") or raw.get("created_at") or "")[:10]
        if not updated or updated < ws or updated > we:
            continue
        touched.append(
            {
                "id": str(raw.get("id") or entry_id),
                "title": str(raw.get("title") or entry_id),
                "updated_at": raw.get("updated_at") or raw.get("created_at"),
            }
        )
    touched.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return touched[:12]


@dataclass
class QuantDigestPayload:
    as_of: date
    week_start: date
    week_end: date
    pnl: dict[str, Any]
    trades: dict[str, Any]
    job_health: dict[str, Any]
    recent_coverage: list[dict[str, Any]]
    playbook_delta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "pnl": self.pnl,
            "trades": self.trades,
            "job_health": self.job_health,
            "recent_coverage": self.recent_coverage,
            "playbook_delta": self.playbook_delta,
        }


def build_quant_digest_payload(
    *,
    as_of: Optional[date] = None,
    pnl_rows: list[Any],
    trades: list[dict[str, Any]],
    job_health: dict[str, Any],
    manifests: list[dict[str, Any]],
    refinements: list[dict[str, Any]],
    playbook_entries: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
    recent_trading_day_count: int = 5,
) -> QuantDigestPayload:
    d = as_of or date.today()
    week_start, week_end = trading_week_range(d)
    pnl = summarize_pnl_rows(pnl_rows, week_start=week_start, week_end=week_end)
    nav = compute_weekly_nav_pnl_from_manifests(manifests, week_start, week_end)
    if nav.get("weekly_pnl") is not None:
        pnl["weekly_pnl"] = nav["weekly_pnl"]
        pnl["weekly_pnl_pct"] = nav.get("weekly_pnl_pct")
        pnl["weekly_pnl_source"] = "nav_manifest"
        if nav.get("start_total") is not None:
            pnl["start_total"] = nav["start_total"]
        if nav.get("end_total") is not None:
            pnl["end_total"] = nav["end_total"]
    else:
        pnl["weekly_pnl_source"] = "daily_pnl_sum"
    trade_summary = summarize_trades(trades)
    health_rows = summarize_job_health_snapshot(job_health)

    recent_days = last_n_trading_days(
        week_end,
        recent_trading_day_count,
        settings=settings,
    )
    by_day = manifest_jobs_by_day(manifests)
    coverage = summarize_recent_job_coverage(recent_days, by_day)

    playbook_delta = {
        "refinements": playbook_delta_from_refinements(
            refinements,
            week_start=week_start,
            week_end=week_end,
        ),
        "entries_touched": playbook_entries_touched_in_week(
            playbook_entries,
            week_start=week_start,
            week_end=week_end,
        ),
    }

    return QuantDigestPayload(
        as_of=d,
        week_start=week_start,
        week_end=week_end,
        pnl=pnl,
        trades=trade_summary,
        job_health={"jobs": health_rows, "recent_trading_days": recent_trading_day_count},
        recent_coverage=coverage,
        playbook_delta=playbook_delta,
    )


def _fmt_pnl(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.2f}"


def render_quant_digest_markdown(payload: QuantDigestPayload | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, QuantDigestPayload) else dict(payload)
    pnl = data.get("pnl") or {}
    trades = data.get("trades") or {}
    health = data.get("job_health") or {}
    coverage = data.get("recent_coverage") or []
    playbook = data.get("playbook_delta") or {}

    lines: list[str] = [
        f"# 量化周报 digest · {data.get('week_start')} ~ {data.get('week_end')}",
        "",
        "## 业绩",
        f"- 周盈亏：**{_fmt_pnl(pnl.get('weekly_pnl'))}**"
        + (
            f"（{pnl.get('weekly_pnl_pct'):+.2f}%）"
            if pnl.get("weekly_pnl_pct") is not None
            else ""
        ),
    ]
    if pnl.get("end_total") is not None:
        lines.append(f"- 周末净值：{float(pnl['end_total']):,.2f}")
    if pnl.get("cumulative_pnl") is not None:
        lines.append(f"- 累计盈亏：{_fmt_pnl(float(pnl['cumulative_pnl']))}")

    daily = pnl.get("daily") or []
    if daily:
        lines.append("")
        lines.append("| 日期 | 日盈亏 | 日涨跌 |")
        lines.append("|------|--------|--------|")
        for row in daily:
            pct = row.get("daily_pnl_pct")
            pct_s = f"{float(pct):+.2f}%" if pct is not None else "—"
            lines.append(
                f"| {row['date']} | {_fmt_pnl(float(row['daily_pnl']))} | {pct_s} |"
            )

    lines.extend(
        [
            "",
            "## 成交",
            f"- 笔数：{trades.get('trade_count', 0)}（买 {trades.get('buys', 0)} / 卖 {trades.get('sells', 0)}）",
            f"- 已实现盈亏：**{_fmt_pnl(trades.get('realized_pnl'))}**",
        ]
    )
    for h in trades.get("highlights") or []:
        lines.append(f"  - {h}")

    lines.extend(["", "## 调度健康（job_health + 近5交易日 manifest）"])
    for row in health.get("jobs") or []:
        streak = int(row.get("consecutive_failures") or 0)
        mark = "✅" if streak == 0 else "⚠️"
        lines.append(
            f"- {mark} **{row.get('job')}** · 连续失败 {streak}"
            + (f" · {row.get('last_error')}" if streak else "")
        )
    for row in coverage:
        mark = "✅" if row.get("ok") else "⚠️"
        miss = ", ".join(row.get("missing") or []) or "—"
        lines.append(f"- {mark} {row.get('date')} 缺 job：{miss}")

    refinements = playbook.get("refinements") or []
    touched = playbook.get("entries_touched") or []
    lines.extend(["", "## Harness playbook Δ"])
    if not refinements and not touched:
        lines.append("- （本周无 playbook 精炼记录）")
    else:
        for r in refinements[:6]:
            lines.append(
                f"- `{r.get('id')}` ({r.get('job')}/{r.get('trigger')}) "
                f"{str(r.get('created_at') or '')[:10]}"
            )
            for ln in r.get("lines") or []:
                lines.append(f"  - {ln}")
        for ent in touched[:6]:
            lines.append(f"- 条目 **{ent.get('title')}** · {str(ent.get('updated_at') or '')[:10]}")

    lines.append("")
    return "\n".join(lines)


def quant_digest_feishu_card(payload: QuantDigestPayload | dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, markdown_body, template_color)."""
    data = payload.to_dict() if isinstance(payload, QuantDigestPayload) else dict(payload)
    pnl = data.get("pnl") or {}
    trades = data.get("trades") or {}
    weekly = float(pnl.get("weekly_pnl") or 0)
    if weekly > 0:
        tpl = "green"
    elif weekly < 0:
        tpl = "red"
    else:
        tpl = "blue"

    title = f"📊 量化周报 digest · {data.get('week_start')}~{data.get('week_end')}"
    body_lines = [
        f"**周盈亏** {_fmt_pnl(pnl.get('weekly_pnl'))}"
        + (
            f"（{pnl.get('weekly_pnl_pct'):+.2f}%）"
            if pnl.get("weekly_pnl_pct") is not None
            else ""
        ),
        f"**成交** {trades.get('trade_count', 0)} 笔 · 已实现 {_fmt_pnl(trades.get('realized_pnl'))}",
    ]
    bad_jobs = [
        j
        for j in (data.get("job_health") or {}).get("jobs") or []
        if int(j.get("consecutive_failures") or 0) > 0
    ]
    if bad_jobs:
        body_lines.append(
            "**告警** "
            + " · ".join(
                f"{j.get('job')}×{j.get('consecutive_failures')}" for j in bad_jobs[:4]
            )
        )
    cov_miss = [c for c in (data.get("recent_coverage") or []) if not c.get("ok")]
    if cov_miss:
        body_lines.append(f"**近5日缺 manifest** {len(cov_miss)} 天")
    pb = data.get("playbook_delta") or {}
    n_pb = len(pb.get("refinements") or []) + len(pb.get("entries_touched") or [])
    if n_pb:
        body_lines.append(f"**Playbook Δ** {n_pb} 条")
    body_lines.append("")
    body_lines.append("_完整 digest 见本地 markdown / cron 日志_")
    return title, "\n".join(body_lines), tpl


def load_and_build_quant_digest(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> QuantDigestPayload:
    from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history
    from agent_reach.daily_run.harness import load_harness
    from agent_reach.daily_run.run_manifest import load_run_manifests_for_range
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.trade_calendar import today_shanghai

    cfg = settings or load_settings()
    d = as_of or today_shanghai()
    week_start, week_end = trading_week_range(d)

    pnl_rows = load_daily_pnl_history(start=week_start, end=week_end, settings=cfg)
    trades = _load_trade_ledger_range(week_start, week_end)

    from agent_reach.daily_run.job_health import _load as load_job_health

    job_health = load_job_health()

    lookback_start = week_start - timedelta(days=14)
    manifests = load_run_manifests_for_range(lookback_start, week_end)

    state = load_harness()
    playbook_entries = {
        eid: ent.to_dict()
        for eid, ent in (state.entries.get("playbook") or {}).items()
    }
    refinements = [e.to_dict() for e in state.refinements]

    return build_quant_digest_payload(
        as_of=d,
        pnl_rows=pnl_rows,
        trades=trades,
        job_health=job_health,
        manifests=manifests,
        refinements=refinements,
        playbook_entries=playbook_entries,
        settings=cfg,
    )
