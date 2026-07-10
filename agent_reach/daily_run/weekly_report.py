# -*- coding: utf-8
"""Weekly trading summary — PnL, holdings, watchlist, hot sectors, sector analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.portfolio_manager import default_ledger_path
from agent_reach.daily_run.run_manifest import runs_dir
from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.symbols import build_enriched_symbols
from agent_reach.daily_run.trade_calendar import today_shanghai


@dataclass
class WeeklyReport:
    week_start: date
    week_end: date
    start_total: Optional[float]
    end_total: Optional[float]
    weekly_pnl: Optional[float]
    weekly_pnl_pct: Optional[float]
    realized_pnl: float
    holdings: list[dict[str, Any]] = field(default_factory=list)
    watchlist: list[dict[str, Any]] = field(default_factory=list)
    hot_sectors: list[dict[str, Any]] = field(default_factory=list)
    sector_groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    mss_summary: list[dict[str, Any]] = field(default_factory=list)
    experience_snippets: list[str] = field(default_factory=list)
    sector_research: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "start_total": self.start_total,
            "end_total": self.end_total,
            "weekly_pnl": self.weekly_pnl,
            "weekly_pnl_pct": self.weekly_pnl_pct,
            "realized_pnl": self.realized_pnl,
            "holdings": self.holdings,
            "watchlist": self.watchlist,
            "hot_sectors": self.hot_sectors,
            "sector_groups": self.sector_groups,
            "trades": self.trades,
            "mss_summary": self.mss_summary,
            "experience_snippets": self.experience_snippets,
            "sector_research": self.sector_research,
            "notes": self.notes,
        }


def trading_week_range(as_of: Optional[date] = None) -> tuple[date, date]:
    """Mon–Fri of the trading week ending on the most recent Friday (Saturday report = just-finished week)."""
    d = as_of or today_shanghai()
    if d.weekday() >= 5:
        friday = d - timedelta(days=d.weekday() - 4)
    else:
        friday = d - timedelta(days=d.weekday() - 4) if d.weekday() <= 4 else d
    monday = friday - timedelta(days=4)
    return monday, friday


def _date_in_range(ds: str, start: date, end: date) -> bool:
    try:
        d = date.fromisoformat(ds[:10])
    except ValueError:
        return False
    return start <= d <= end


def _iter_manifest_files(start: date, end: date) -> list[tuple[date, Path]]:
    root = runs_dir()
    if not root.exists():
        return []
    out: list[tuple[date, Path]] = []
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        for path in sorted(day_dir.glob("*.json")):
            out.append((day, path))
    return out


def _load_manifest(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _portfolio_total_from_manifest(record: dict[str, Any]) -> Optional[float]:
    payload = record.get("payload") or {}
    for key in ("result",):
        block = payload.get(key) or {}
        snap = block.get("snapshot") or {}
        pf = snap.get("portfolio") or {}
        total = pf.get("total")
        if total is not None:
            return float(total)
    return None


def _mss_from_manifest(record: dict[str, Any]) -> Optional[float]:
    payload = record.get("payload") or {}
    result = payload.get("result") or {}
    snap = result.get("snapshot") or {}
    if snap.get("mss_final") is not None:
        return float(snap["mss_final"])
    verify = result.get("verify") or {}
    if verify.get("mss_current") is not None:
        return float(verify["mss_current"])
    evaluation = result.get("evaluation") or {}
    report = evaluation.get("report") or {}
    if report.get("mss_final") is not None:
        return float(report["mss_final"])
    return None


def _load_week_manifests(start: date, end: date) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for day, path in _iter_manifest_files(start, end):
        record = _load_manifest(path)
        if record:
            record["_run_date"] = day.isoformat()
            record["_path"] = str(path)
            records.append(record)
    return records


def _load_trade_ledger_range(start: date, end: date) -> list[dict[str, Any]]:
    path = default_ledger_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = str(entry.get("at") or "")
        if not _date_in_range(at, start, end):
            continue
        entries.append(entry)
    return entries


def _compute_realized_pnl(trades: list[dict[str, Any]]) -> float:
    """Approximate realized PnL from ledger buy/sell actions (sell proceeds − buy cost)."""
    pnl = 0.0
    for entry in trades:
        for action in entry.get("actions") or []:
            side = action.get("side")
            amount = float(action.get("amount") or 0)
            commission = float(action.get("commission") or 0)
            if side == "sell":
                pnl += amount - commission
            elif side == "buy":
                pnl -= amount + commission
    return round(pnl, 2)


def _holding_pnl_rows(
    portfolio: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    week_start_prices: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in portfolio.get("holdings") or []:
        code = _normalize_code(str(h.get("code", "")))
        name = h.get("name") or code
        shares = int(h.get("shares") or 0)
        cost = float(h.get("cost") or 0)
        row = enriched.get(code, {})
        price = row.get("price") or h.get("price") or cost
        price = float(price)
        mv = round(shares * price, 2)
        cost_basis = round(shares * cost, 2)
        unrealized = round(mv - cost_basis, 2)
        unrealized_pct = round(unrealized / cost_basis * 100, 2) if cost_basis else None
        week_start = week_start_prices.get(code)
        week_chg = None
        week_chg_pct = None
        if week_start and week_start > 0:
            week_chg = round((price - week_start) * shares, 2)
            week_chg_pct = round((price - week_start) / week_start * 100, 2)
        rows.append(
            {
                "code": code,
                "name": name,
                "shares": shares,
                "price": price,
                "cost": cost,
                "market_value": mv,
                "unrealized_pnl": unrealized,
                "unrealized_pct": unrealized_pct,
                "week_chg": week_chg,
                "week_chg_pct": week_chg_pct,
                "change_pct": row.get("change_pct"),
                "sector": row.get("sector") or row.get("industry") or h.get("sector") or h.get("industry"),
            }
        )
    rows.sort(key=lambda x: x.get("market_value") or 0, reverse=True)
    return rows


def _watchlist_rows(portfolio: dict[str, Any], enriched: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    held = {
        _normalize_code(str(h.get("code", "")))
        for h in portfolio.get("holdings") or []
        if _normalize_code(str(h.get("code", "")))
    }
    rows: list[dict[str, Any]] = []
    for w in portfolio.get("watchlist") or []:
        code = _normalize_code(str(w.get("code", "")))
        if not code or code in held:
            continue
        row = {**dict(w), **enriched.get(code, {})}
        rows.append(
            {
                "code": code,
                "name": row.get("name") or code,
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "sector": row.get("sector") or row.get("industry"),
            }
        )
    rows.sort(
        key=lambda x: float(x["change_pct"]) if x.get("change_pct") is not None else -999,
        reverse=True,
    )
    return rows


def _identify_hot_sectors(enriched: dict[str, dict[str, Any]], *, min_change: float = 1.0, limit: int = 8) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for code, row in enriched.items():
        chg = row.get("change_pct")
        if chg is None:
            continue
        chg_f = float(chg)
        if chg_f >= min_change:
            items.append(
                {
                    "code": code,
                    "name": row.get("name") or code,
                    "change_pct": chg_f,
                    "sector": row.get("sector") or row.get("industry") or "未分类",
                }
            )
    items.sort(key=lambda x: x["change_pct"], reverse=True)
    return items[:limit]


def _group_by_sector(enriched: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for code, row in enriched.items():
        sector = row.get("sector") or row.get("industry") or "综合"
        groups.setdefault(str(sector), []).append({**row, "code": code})
    for sector in groups:
        groups[sector].sort(
            key=lambda x: float(x.get("change_pct") or 0),
            reverse=True,
        )
    return dict(sorted(groups.items(), key=lambda kv: -max(float(x.get("change_pct") or 0) for x in kv[1])))


def build_sector_research_queries(sector_groups: dict[str, list[dict[str, Any]]], *, limit: int = 3) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []
    for sector, symbols in list(sector_groups.items())[:limit]:
        if sector == "综合":
            continue
        top = symbols[0] if symbols else {}
        label = f"{sector} 板块"
        names = " ".join(str(s.get("name") or s.get("code")) for s in symbols[:3])
        queries.append(
            {
                "type": "sector",
                "query": f"China A-share {sector} sector outlook weekly analysis 2026 {names}",
                "label": label,
            }
        )
    return queries


def run_sector_research(
    queries: list[dict[str, str]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from agent_reach.daily_run.exa_client import ExaError, is_exa_available, summarize_hits, web_search_exa

    cfg = settings.get("weekly_report") or {}
    if cfg.get("exa_sector_research", True) is False:
        return []
    if not is_exa_available():
        return []

    plugin_cfg = settings.get("plugins") or {}
    timeout = int(plugin_cfg.get("exa_timeout", 45))
    max_q = int(cfg.get("max_sector_queries", 3))
    queries = queries[:max_q]
    if not queries:
        return []

    def _run_one(q: dict[str, str]) -> dict[str, Any]:
        try:
            hits = web_search_exa(q["query"], num_results=3, timeout=timeout)
            return {**q, "hits": hits, "summary": summarize_hits(hits), "success": True}
        except ExaError as exc:
            return {**q, "hits": [], "summary": str(exc), "success": False}

    workers = min(len(queries), 3)
    ordered: list[Optional[dict[str, Any]]] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one, q): i for i, q in enumerate(queries)}
        for fut in as_completed(futures):
            ordered[futures[fut]] = fut.result()
    return [r for r in ordered if r is not None]


def _load_experience_snippets(start: date, end: date, limit: int = 5) -> list[str]:
    from agent_reach.daily_run.experience import load_recent_experience

    recent = load_recent_experience(limit=50)
    snippets: list[str] = []
    for e in recent:
        ds = str(e.get("date") or "")
        if not _date_in_range(ds, start, end):
            continue
        hit = "✅" if e.get("prediction_hit") else "—"
        rules = "；".join((e.get("rules") or [])[:2])
        snippets.append(
            f"{ds} {e.get('name')} MSS={e.get('mss_final')} {hit} {rules}".strip()
        )
        if len(snippets) >= limit:
            break
    return snippets


def generate_weekly_report(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    as_of: Optional[date] = None,
    portfolio: Optional[dict[str, Any]] = None,
) -> WeeklyReport:
    """Aggregate Mon–Fri manifests, ledger, portfolio into a weekly summary."""
    week_start, week_end = trading_week_range(as_of)
    pf = portfolio or (snapshot.get("portfolio") or {})
    enriched = build_enriched_symbols(snapshot)
    manifests = _load_week_manifests(week_start, week_end)
    trades = _load_trade_ledger_range(week_start, week_end)
    realized = _compute_realized_pnl(trades)

    start_total: Optional[float] = None
    end_total: Optional[float] = None
    week_start_prices: dict[str, float] = {}
    mss_summary: list[dict[str, Any]] = []
    notes: list[str] = []

    morning_totals: list[tuple[str, float]] = []
    close_totals: list[tuple[str, float]] = []
    for record in manifests:
        job = record.get("job")
        day = record.get("_run_date", "")
        total = _portfolio_total_from_manifest(record)
        if job == "morning" and total is not None:
            morning_totals.append((day, total))
        if job == "close" and total is not None:
            close_totals.append((day, total))
        mss = _mss_from_manifest(record)
        if mss is not None and job in ("morning", "close", "intraday"):
            mss_summary.append({"date": day, "job": job, "mss_final": mss})

    if morning_totals:
        morning_totals.sort(key=lambda x: x[0])
        start_total = morning_totals[0][1]
    if close_totals:
        close_totals.sort(key=lambda x: x[0])
        end_total = close_totals[-1][1]

    if end_total is None:
        end_total = float(pf.get("total") or 0) or None
    if start_total is None and end_total is not None:
        start_total = end_total
        notes.append("本周无早盘 manifest，周初净值用周末/当前估值代替")

    weekly_pnl: Optional[float] = None
    weekly_pnl_pct: Optional[float] = None
    if start_total is not None and end_total is not None:
        weekly_pnl = round(end_total - start_total, 2)
        if start_total:
            weekly_pnl_pct = round(weekly_pnl / start_total * 100, 2)

    holdings = _holding_pnl_rows(pf, enriched, week_start_prices)
    watchlist = _watchlist_rows(pf, enriched)
    hot_sectors = _identify_hot_sectors(enriched)
    sector_groups = _group_by_sector(enriched)
    experience_snippets = _load_experience_snippets(week_start, week_end)

    sector_queries = build_sector_research_queries(sector_groups)
    sector_research = run_sector_research(sector_queries, settings)

    return WeeklyReport(
        week_start=week_start,
        week_end=week_end,
        start_total=start_total,
        end_total=end_total,
        weekly_pnl=weekly_pnl,
        weekly_pnl_pct=weekly_pnl_pct,
        realized_pnl=realized,
        holdings=holdings,
        watchlist=watchlist,
        hot_sectors=hot_sectors,
        sector_groups=sector_groups,
        trades=trades,
        mss_summary=mss_summary[-10:],
        experience_snippets=experience_snippets,
        sector_research=sector_research,
        notes=notes,
    )


def render_weekly_markdown(report: WeeklyReport) -> str:
    """Render Feishu-friendly weekly summary markdown."""
    lines: list[str] = []
    ws, we = report.week_start.isoformat(), report.week_end.isoformat()
    lines.append(f"**📅 周期：** {ws} ~ {we}")
    lines.append("")

    lines.append("## 💰 本周盈亏")
    if report.weekly_pnl is not None:
        sign = "+" if report.weekly_pnl >= 0 else ""
        pct = ""
        if report.weekly_pnl_pct is not None:
            pct = f"（{sign}{report.weekly_pnl_pct}%）"
        lines.append(
            f"- **组合净值变动：** {sign}¥{report.weekly_pnl:,.2f}{pct}"
        )
        if report.start_total is not None and report.end_total is not None:
            lines.append(
                f"- 周初 ¥{report.start_total:,.2f} → 周末 ¥{report.end_total:,.2f}"
            )
    else:
        lines.append("- 暂无完整净值数据（需本周 daily-run manifest）")
    if report.realized_pnl:
        sign = "+" if report.realized_pnl >= 0 else ""
        lines.append(f"- **本周成交净额（ledger）：** {sign}¥{report.realized_pnl:,.2f}")
    if report.trades:
        lines.append(f"- 成交笔数：**{len(report.trades)}**")
    for note in report.notes:
        lines.append(f"- _{note}_")
    lines.append("")

    lines.append("## 📊 持股")
    if report.holdings:
        for h in report.holdings:
            chg = h.get("change_pct")
            chg_s = f" 今日 {float(chg):+.2f}%" if chg is not None else ""
            upnl = h.get("unrealized_pnl")
            upnl_s = f" 浮盈 ¥{upnl:+,.0f}" if upnl is not None else ""
            week_s = ""
            if h.get("week_chg_pct") is not None:
                week_s = f" 本周 {h['week_chg_pct']:+.2f}%"
            lines.append(
                f"- **{h['name']}** ({h['code']}) {h['shares']}股 "
                f"@ ¥{h['price']:.2f} 市值 ¥{h['market_value']:,.0f}{upnl_s}{chg_s}{week_s}"
            )
    else:
        lines.append("- 当前无持仓")
    lines.append("")

    lines.append("## 👀 观察池")
    if report.watchlist:
        for w in report.watchlist:
            chg = w.get("change_pct")
            chg_s = f" {float(chg):+.2f}%" if chg is not None else ""
            price_s = f"¥{float(w['price']):.2f} " if w.get("price") else ""
            lines.append(f"- **{w['name']}** ({w['code']}) {price_s}{chg_s}")
    else:
        lines.append("- 观察池为空或标的已在持仓中")
    lines.append("")

    lines.append("## 🔥 热门板块 / 强势标的")
    if report.hot_sectors:
        for item in report.hot_sectors:
            lines.append(
                f"- **{item['name']}** ({item['code']}) {item['change_pct']:+.2f}% · {item['sector']}"
            )
    else:
        lines.append("- 本周暂无涨幅 >1% 的持仓/观察标的")
    lines.append("")

    lines.append("## 🏭 板块分析")
    if report.sector_groups:
        for sector, symbols in list(report.sector_groups.items())[:6]:
            parts = []
            for s in symbols[:4]:
                name = s.get("name") or s.get("code")
                chg = s.get("change_pct")
                if chg is not None:
                    parts.append(f"{name} {float(chg):+.1f}%")
                else:
                    parts.append(str(name))
            lines.append(f"- **{sector}：** " + "、".join(parts))
    else:
        lines.append("- 无板块分组数据")
    lines.append("")

    if report.sector_research:
        lines.append("### 板块深度（Exa）")
        for r in report.sector_research:
            status = "✅" if r.get("success") else "⚠️"
            lines.append(f"**{status} {r.get('label', '板块')}**")
            if r.get("summary"):
                lines.append(r["summary"])
            lines.append("")

    if report.mss_summary:
        lines.append("## 📈 MSS 本周轨迹")
        for row in report.mss_summary:
            lines.append(f"- {row['date']} {row['job']} MSS={row['mss_final']:.1f}")
        lines.append("")

    if report.experience_snippets:
        lines.append("## 📚 本周经验")
        for s in report.experience_snippets:
            lines.append(f"- {s}")
        lines.append("")

    return "\n".join(lines).strip()


def weekly_report_title(report: WeeklyReport) -> str:
    pnl_part = ""
    if report.weekly_pnl is not None:
        sign = "+" if report.weekly_pnl >= 0 else ""
        pnl_part = f" · {sign}¥{report.weekly_pnl:,.0f}"
    return f"📋 周报总结 · {report.week_start:%m/%d}–{report.week_end:%m/%d}{pnl_part}"
