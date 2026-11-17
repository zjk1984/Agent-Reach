# -*- coding: utf-8
"""Read-only ledger ↔ portfolio reconciliation (AR-6)."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.portfolio_manager import default_ledger_path
from agent_reach.daily_run.realized_pnl import (
    _apply_buy,
    _apply_sell,
    _lot_shares,
    _lot_tuple,
    compute_trade_cash_flow,
    load_ledger_entries,
    opening_costs_from_portfolio,
)
from agent_reach.daily_run.snapshot_builder import default_portfolio_path, load_portfolio
from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import today_shanghai


@dataclass
class HoldingVariance:
    code: str
    name: str
    portfolio_shares: int
    ledger_shares: int
    portfolio_cost: Optional[float]
    ledger_avg_cost: Optional[float]
    shares_match: bool
    cost_match: bool
    cost_delta: Optional[float]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "portfolio_shares": self.portfolio_shares,
            "ledger_shares": self.ledger_shares,
            "portfolio_cost": self.portfolio_cost,
            "ledger_avg_cost": self.ledger_avg_cost,
            "shares_match": self.shares_match,
            "cost_match": self.cost_match,
            "cost_delta": self.cost_delta,
            "notes": list(self.notes),
        }


@dataclass
class CostMarkRow:
    code: str
    name: str
    day: str
    portfolio_cost: Optional[float]
    portfolio_price: Optional[float]
    quote_source: Optional[str]
    manifest_close: Optional[float]
    mark_price: Optional[float]
    cost_equals_price: bool
    cost_fallback: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "notes"} | {"notes": list(self.notes)}


@dataclass
class LedgerReconcileResult:
    as_of: str
    dry_run: bool
    ledger_path: str
    portfolio_path: str
    seed_source: str
    seed_holdings_count: int
    ledger_entries: int
    holdings: list[HoldingVariance]
    cash_portfolio: Optional[float]
    cash_ledger_expected: Optional[float]
    cash_drift: Optional[float]
    trade_cash_flow_total: float
    journal: dict[str, Any]
    cost_marks: list[CostMarkRow]
    warnings: list[str]
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "dry_run": self.dry_run,
            "ledger_path": self.ledger_path,
            "portfolio_path": self.portfolio_path,
            "seed_source": self.seed_source,
            "seed_holdings_count": self.seed_holdings_count,
            "ledger_entries": self.ledger_entries,
            "holdings": [h.to_dict() for h in self.holdings],
            "cash_portfolio": self.cash_portfolio,
            "cash_ledger_expected": self.cash_ledger_expected,
            "cash_drift": self.cash_drift,
            "trade_cash_flow_total": self.trade_cash_flow_total,
            "journal": self.journal,
            "cost_marks": [r.to_dict() for r in self.cost_marks],
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


def _seed_lots_from_holdings(holdings: list[dict[str, Any]]) -> dict[str, deque]:
    lots: dict[str, deque] = {}
    for h in holdings:
        code = _normalize_code(str(h.get("code") or ""))
        shares = int(h.get("shares") or 0)
        cost = float(h.get("cost") or 0)
        if code and shares > 0 and cost > 0:
            lots.setdefault(code, deque()).append(_lot_tuple(shares, cost, ""))
    return lots


def _avg_cost_from_lots(queue: deque) -> Optional[float]:
    total_shares = _lot_shares(queue)
    if total_shares <= 0:
        return None
    basis = sum(sh * cost for sh, cost, _ in queue)
    return round(basis / total_shares, 4)


def replay_holdings_from_ledger(
    trades: list[dict[str, Any]],
    *,
    seed_holdings: Optional[list[dict[str, Any]]] = None,
    opening_costs: Optional[dict[str, float]] = None,
) -> dict[str, dict[str, Any]]:
    """FIFO replay → shares + weighted avg cost per symbol (after seed + ledger)."""
    lots = _seed_lots_from_holdings(seed_holdings or [])
    costs = dict(opening_costs or {})
    for h in seed_holdings or []:
        code = _normalize_code(str(h.get("code") or ""))
        cost = float(h.get("cost") or 0)
        if code and cost > 0:
            costs.setdefault(code, cost)

    for entry in trades:
        entry_at = str(entry.get("at") or "")
        day = entry_at[:10]
        for action in entry.get("actions") or []:
            side = action.get("side")
            if side == "buy":
                _apply_buy(lots, action, buy_date=day)
            elif side == "sell":
                _apply_sell(lots, action, sell_date=day, opening_costs=costs)

    out: dict[str, dict[str, Any]] = {}
    for code, queue in lots.items():
        shares = _lot_shares(queue)
        if shares <= 0:
            continue
        out[code] = {
            "shares": shares,
            "avg_cost": _avg_cost_from_lots(queue),
        }
    return out


def _load_seed_portfolio(settings: Optional[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, Optional[float]]:
    """Morning baseline holdings + cash for ledger cash reconcile."""
    try:
        from agent_reach.daily_run.workflows import load_morning_baseline

        baseline = load_morning_baseline()
        pf = baseline.get("portfolio") or baseline
        holdings = list(pf.get("holdings") or [])
        cash = pf.get("cash")
        cash_f = float(cash) if cash is not None else None
        if holdings:
            return holdings, "last_morning.json", cash_f
    except Exception:
        pass

    cfg = settings or {}
    seed_path = cfg.get("ledger_reconcile", {}).get("seed_portfolio_path")
    if seed_path:
        p = Path(str(seed_path)).expanduser()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            pf = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else data
            holdings = list(pf.get("holdings") or [])
            cash = pf.get("cash")
            return holdings, str(p), float(cash) if cash is not None else None

    return [], "none", None


def _compare_holdings(
    portfolio: dict[str, Any],
    ledger_holdings: dict[str, dict[str, Any]],
    *,
    cost_tolerance: float = 0.02,
) -> list[HoldingVariance]:
    pf_by_code: dict[str, dict[str, Any]] = {}
    for h in portfolio.get("holdings") or []:
        code = _normalize_code(str(h.get("code") or ""))
        if code:
            pf_by_code[code] = h

    codes = sorted(set(pf_by_code) | set(ledger_holdings))
    rows: list[HoldingVariance] = []
    for code in codes:
        pf = pf_by_code.get(code) or {}
        led = ledger_holdings.get(code) or {}
        pf_sh = int(pf.get("shares") or 0)
        led_sh = int(led.get("shares") or 0)
        pf_cost = float(pf["cost"]) if pf.get("cost") is not None else None
        led_cost = led.get("avg_cost")
        led_cost_f = float(led_cost) if led_cost is not None else None
        shares_match = pf_sh == led_sh
        cost_match = True
        cost_delta = None
        notes: list[str] = []
        if pf_cost is not None and led_cost_f is not None:
            cost_delta = round(pf_cost - led_cost_f, 4)
            cost_match = abs(cost_delta) <= cost_tolerance
        elif pf_sh > 0 and led_cost_f is None:
            notes.append("ledger 回放缺少成本（检查 seed 持仓）")
            cost_match = False
        elif led_sh > 0 and pf_cost is None:
            notes.append("portfolio 缺 cost 字段")
            cost_match = False
        rows.append(
            HoldingVariance(
                code=code,
                name=str(pf.get("name") or code),
                portfolio_shares=pf_sh,
                ledger_shares=led_sh,
                portfolio_cost=pf_cost,
                ledger_avg_cost=led_cost_f,
                shares_match=shares_match,
                cost_match=cost_match,
                cost_delta=cost_delta,
                notes=notes,
            )
        )
    return rows


def _marks_from_close_manifest(day: date, code: str) -> tuple[Optional[float], list[str]]:
    from agent_reach.daily_run.run_manifest import runs_dir

    notes: list[str] = []
    day_dir = runs_dir() / day.isoformat()
    if not day_dir.is_dir():
        notes.append("无收盘 manifest")
        return None, notes

    norm = _normalize_code(code)
    for path in sorted(day_dir.glob("close_*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        payload = record.get("payload") or {}
        for row in payload.get("symbol_results") or []:
            if _normalize_code(str(row.get("code") or "")) != norm:
                continue
            snap = (row.get("result") or {}).get("snapshot") or {}
            price = snap.get("price")
            if price is not None:
                notes.append(f"manifest {path.name}")
                return float(price), notes
        # Per-symbol close manifest
        snap = (payload.get("result") or {}).get("snapshot") or {}
        if _normalize_code(str(snap.get("code") or "")) == norm and snap.get("price") is not None:
            notes.append(f"manifest {path.name}")
            return float(snap["price"]), notes
    notes.append("manifest 未找到该标的收盘价")
    return None, notes


def gather_cost_marks(
    portfolio: dict[str, Any],
    *,
    codes: list[str],
    mark_days: list[date],
) -> list[CostMarkRow]:
    from agent_reach.daily_run.quote_coverage import mark_price_from_row

    pf_by_code: dict[str, dict[str, Any]] = {}
    for h in portfolio.get("holdings") or []:
        c = _normalize_code(str(h.get("code") or ""))
        if c:
            pf_by_code[c] = h

    rows: list[CostMarkRow] = []
    for day in mark_days:
        ds = day.isoformat()
        for raw in codes:
            code = _normalize_code(raw)
            h = pf_by_code.get(code) or {"code": code, "name": code}
            pf_cost = float(h["cost"]) if h.get("cost") is not None else None
            pf_price = float(h["price"]) if h.get("price") is not None else None
            qs = str(h.get("quote_source") or "") or None
            manifest_px, mnotes = _marks_from_close_manifest(day, code)
            probe = dict(h)
            mark = mark_price_from_row(probe, {})
            cost_fb = qs == "cost_fallback"
            eq = (
                pf_cost is not None
                and pf_price is not None
                and abs(pf_price - pf_cost) < 0.0001
            )
            notes = list(mnotes)
            if eq and mark is None:
                notes.append("price≈cost 且 mark_price 无效（历史 cost-as-mark 症状）")
            if day.isoformat() == str(portfolio.get("trade_session_date") or "")[:10]:
                notes.append("portfolio trade_session 当日")
            rows.append(
                CostMarkRow(
                    code=code,
                    name=str(h.get("name") or code),
                    day=ds,
                    portfolio_cost=pf_cost,
                    portfolio_price=pf_price,
                    quote_source=qs,
                    manifest_close=manifest_px,
                    mark_price=mark,
                    cost_equals_price=eq,
                    cost_fallback=cost_fb,
                    notes=notes,
                )
            )
    return rows


def run_ledger_reconcile(
    *,
    as_of: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
    ledger_path: Optional[Path] = None,
    portfolio_path: Optional[Path] = None,
    focus_codes: Optional[list[str]] = None,
    mark_dates: Optional[list[date]] = None,
    dry_run: bool = True,
    cost_tolerance: float = 0.02,
    cash_tolerance: float = 1.0,
) -> LedgerReconcileResult:
    day = as_of or today_shanghai()
    lp = ledger_path or default_ledger_path()
    pp = portfolio_path or default_portfolio_path()
    portfolio = load_portfolio(path=pp) if pp.is_file() else {"holdings": []}

    seed_holdings, seed_source, seed_cash = _load_seed_portfolio(settings)
    entries = load_ledger_entries(path=lp, end=day, settings=settings)
    opening = opening_costs_from_portfolio({"holdings": seed_holdings})
    ledger_holdings = replay_holdings_from_ledger(
        entries,
        seed_holdings=seed_holdings,
        opening_costs=opening or None,
    )
    variances = _compare_holdings(portfolio, ledger_holdings, cost_tolerance=cost_tolerance)

    trade_flow = compute_trade_cash_flow(entries)
    cash_pf = float(portfolio["cash"]) if portfolio.get("cash") is not None else None
    cash_expected: Optional[float] = None
    cash_drift: Optional[float] = None
    warnings: list[str] = []

    if seed_cash is not None and cash_pf is not None:
        cash_expected = round(float(seed_cash) + trade_flow, 2)
        cash_drift = round(cash_pf - cash_expected, 2)
        if abs(cash_drift) > cash_tolerance:
            warnings.append(
                f"现金偏差 ¥{cash_drift:+,.2f}（portfolio ¥{cash_pf:,.2f} vs ledger 推算 ¥{cash_expected:,.2f}）"
            )
    else:
        warnings.append("未推算现金：缺少 morning baseline cash seed")

    if not seed_holdings:
        warnings.append(
            "未加载 seed 持仓：ledger 回放可能低估期初仓位（请配置 last_morning 或 ledger_reconcile.seed_portfolio_path）"
        )

    codes = focus_codes or ["002583", "000725"]
    mark_days = mark_dates or [date(2026, 10, 22), date(2026, 10, 23)]
    cost_marks = gather_cost_marks(portfolio, codes=codes, mark_days=mark_days)

    from agent_reach.daily_run.harness_finance import run_finance_ledger_checks

    pf_summary = {
        "as_of": day.isoformat(),
        "trades": entries,
        "trade_cash_flow": trade_flow,
    }
    journal = run_finance_ledger_checks(pf_summary, trades=entries, settings=settings)

    mismatch = [v for v in variances if not v.shares_match or not v.cost_match]
    if mismatch:
        warnings.append(f"{len(mismatch)} 只持仓与 ledger 回放不一致")
    if variances:
        pnl_warn = []
        for v in variances:
            if v.portfolio_shares > 0 and v.cost_delta is not None and abs(v.cost_delta) > cost_tolerance:
                pnl_warn.append(f"{v.code} cost Δ{v.cost_delta:+.4f}")
        if pnl_warn:
            warnings.append("ledger vs portfolio PnL 双读 warning: " + "; ".join(pnl_warn))

    ok = not mismatch and not any("现金偏差" in w for w in warnings) and bool(journal.get("passed"))

    return LedgerReconcileResult(
        as_of=day.isoformat(),
        dry_run=dry_run,
        ledger_path=str(lp),
        portfolio_path=str(pp),
        seed_source=seed_source,
        seed_holdings_count=len(seed_holdings),
        ledger_entries=len(entries),
        holdings=variances,
        cash_portfolio=cash_pf,
        cash_ledger_expected=cash_expected,
        cash_drift=cash_drift,
        trade_cash_flow_total=trade_flow,
        journal=journal,
        cost_marks=cost_marks,
        warnings=warnings,
        ok=ok,
    )


def render_ledger_reconcile_markdown(result: LedgerReconcileResult | dict[str, Any]) -> str:
    data = result.to_dict() if isinstance(result, LedgerReconcileResult) else result
    lines = [
        "# Ledger ↔ Portfolio 对账（只读）",
        "",
        f"- **as_of:** {data.get('as_of')}",
        f"- **mode:** {'dry-run' if data.get('dry_run') else 'apply（未实现写操作）'}",
        f"- **ledger:** `{data.get('ledger_path')}` ({data.get('ledger_entries')} 条)",
        f"- **portfolio:** `{data.get('portfolio_path')}`",
        f"- **seed:** {data.get('seed_source')} ({data.get('seed_holdings_count')} 持仓)",
        f"- **status:** {'✅ OK' if data.get('ok') else '⚠️ 有差异'}",
        "",
    ]

    if data.get("warnings"):
        lines.append("## 警告")
        for w in data["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## 持仓：portfolio vs ledger FIFO 回放")
    lines.append("| 代码 | 名称 | pf股 | ledger股 | pf成本 | ledger均本 | 股数 | 成本 |")
    lines.append("|------|------|------|----------|--------|------------|------|------|")
    for h in data.get("holdings") or []:
        sh = "✅" if h.get("shares_match") else "❌"
        co = "✅" if h.get("cost_match") else "❌"
        lines.append(
            f"| {h.get('code')} | {h.get('name')} | {h.get('portfolio_shares')} | "
            f"{h.get('ledger_shares')} | {h.get('portfolio_cost')} | {h.get('ledger_avg_cost')} | {sh} | {co} |"
        )
    lines.append("")

    if data.get("cash_portfolio") is not None:
        lines.extend(
            [
                "## 现金",
                f"- portfolio cash: ¥{float(data['cash_portfolio']):,.2f}",
                f"- ledger 推算: ¥{float(data.get('cash_ledger_expected') or 0):,.2f} "
                f"(seed + 成交现金流 {float(data.get('trade_cash_flow_total') or 0):+,.2f})",
                f"- 偏差: ¥{float(data.get('cash_drift') or 0):+,.2f}",
                "",
            ]
        )

    marks = data.get("cost_marks") or []
    if marks:
        lines.append("## 成本 / 收盘标记（002583 · 000725 等）")
        lines.append("| 日期 | 代码 | pf成本 | pf价 | quote_source | manifest收盘 | mark_price | 价=成本 |")
        lines.append("|------|------|--------|------|--------------|-------------|------------|---------|")
        for r in marks:
            eq = "⚠️" if r.get("cost_equals_price") else "—"
            lines.append(
                f"| {r.get('day')} | {r.get('code')} | {r.get('portfolio_cost')} | {r.get('portfolio_price')} | "
                f"{r.get('quote_source') or '—'} | {r.get('manifest_close')} | {r.get('mark_price')} | {eq} |"
            )
        lines.append("")

    journal = data.get("journal") or {}
    j = journal.get("journal") or {}
    lines.extend(
        [
            "## Ledger 分录校验",
            f"- balanced: {j.get('balanced')} · actions: {j.get('actions_checked')}",
        ]
    )
    for flag in j.get("blocking_flags") or []:
        lines.append(f"- blocking: {flag}")
    for flag in j.get("review_flags") or []:
        lines.append(f"- review: {flag}")

    lines.append("")
    lines.append(
        "_weekly 收盘=成本 展示问题已于 #133/#135 修复；本命令不重算历史 Feishu 卡片。_"
    )
    return "\n".join(lines)