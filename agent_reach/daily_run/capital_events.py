# -*- coding: utf-8
"""Track external capital deposits/withdrawals for accurate daily P&L."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


@dataclass
class CapitalEvent:
    date: str
    kind: str  # deposit | withdraw
    amount: float
    note: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "kind": self.kind,
            "amount": round(float(self.amount), 2),
            "note": self.note,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> CapitalEvent:
        return cls(
            date=str(row.get("date") or ""),
            kind=str(row.get("kind") or ""),
            amount=float(row.get("amount") or 0),
            note=str(row.get("note") or ""),
            at=str(row.get("at") or ""),
        )


def default_capital_events_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "capital_events.jsonl"


def append_capital_event(
    kind: str,
    amount: float,
    *,
    note: str = "",
    event_date: Optional[date] = None,
    path: Optional[Path] = None,
) -> CapitalEvent:
    kind_norm = kind.strip().lower()
    if kind_norm not in ("deposit", "withdraw"):
        raise ValueError("kind must be deposit or withdraw")
    amt = float(amount)
    if amt <= 0:
        raise ValueError("amount must be positive")

    day = event_date or today_shanghai()
    event = CapitalEvent(
        date=day.isoformat(),
        kind=kind_norm,
        amount=round(amt, 2),
        note=note.strip(),
        at=datetime.now(timezone.utc).isoformat(),
    )
    p = path or default_capital_events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    try:
        from agent_reach.daily_run.storage.hooks import on_capital_event

        on_capital_event(event.to_dict(), source_path=str(p))
    except Exception:
        pass
    return event


def load_capital_events(
    *,
    path: Optional[Path] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> list[CapitalEvent]:
    p = path or default_capital_events_path()
    try:
        from agent_reach.daily_run.settings import load_settings
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_capital_events

        if storage_db_reads_allowed(settings, file_path=p, explicit_path=path is not None):
            cfg = settings or load_settings()
            db_rows = read_capital_events(settings=cfg, start=start, end=end)
            if db_rows:
                return [CapitalEvent.from_dict(row) for row in db_rows]
    except Exception:
        pass
    if not p.is_file():
        return []
    out: list[CapitalEvent] = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = CapitalEvent.from_dict(row)
            if not event.date:
                continue
            if start is not None and event.date < start.isoformat():
                continue
            if end is not None and event.date > end.isoformat():
                continue
            out.append(event)
    return out


def net_capital_flow(
    day: date,
    *,
    path: Optional[Path] = None,
) -> float:
    """Net external flow for one day: deposits positive, withdrawals negative."""
    events = load_capital_events(path=path, start=day, end=day)
    total = 0.0
    for event in events:
        if event.kind == "deposit":
            total += float(event.amount)
        elif event.kind == "withdraw":
            total -= float(event.amount)
    return round(total, 2)


def apply_capital_event_to_portfolio(
    portfolio: dict[str, Any],
    kind: str,
    amount: float,
) -> dict[str, Any]:
    """Apply a deposit/withdraw's cash delta to `portfolio` (cash + total in lockstep).

    A capital event doesn't change any holding's market value, so `total` can be
    shifted by the same delta as `cash` without a fresh quote/enriched-symbols
    fetch. Intended to be called right alongside `append_capital_event` (see the
    `daily-run capital deposit/withdraw` CLI) so the ledger event and the
    portfolio balance never drift apart — logging one without the other is what
    causes `close_code_review`'s cash-vs-ledger check to (correctly, but
    unhelpfully) treat a real deposit/withdrawal as unexplained drift.
    """
    kind_norm = kind.strip().lower()
    if kind_norm not in ("deposit", "withdraw"):
        raise ValueError("kind must be deposit or withdraw")
    amt = float(amount)
    if amt <= 0:
        raise ValueError("amount must be positive")
    delta = amt if kind_norm == "deposit" else -amt

    pf = dict(portfolio)
    pf["cash"] = round(float(pf.get("cash") or 0) + delta, 2)
    if pf.get("total") is not None:
        new_total = round(float(pf["total"]) + delta, 2)
        pf["total"] = new_total
        pf["cash_ratio"] = round(pf["cash"] / new_total, 4) if new_total > 0 else 1.0
    return pf


def format_capital_flow_note(net_flow: float) -> str:
    if abs(net_flow) < 0.01:
        return ""
    if net_flow > 0:
        return f"已剔除入金 **¥{net_flow:,.0f}**"
    return f"已剔除出金 **¥{abs(net_flow):,.0f}**"
