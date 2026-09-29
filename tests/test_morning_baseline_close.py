# -*- coding: utf-8
"""Morning baseline loading and close cash reconcile guards."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.daily_run.close_portfolio_summary import apply_portfolio_cash_reconcile
from agent_reach.daily_run.workflows import (
    _baseline_session_date,
    _load_morning_baseline_from_holdings,
    load_morning_baseline,
    morning_baseline_path,
)


def test_baseline_session_date_parses_saved_at():
    data = {"baseline_saved_at": "2026-09-29T00:02:15.900158+00:00"}
    assert _baseline_session_date(data) == date(2026, 9, 29)


def test_load_morning_baseline_from_holdings_prefers_today(tmp_path, monkeypatch):
    base = tmp_path / "daily_run"
    (base / "baselines" / "morning").mkdir(parents=True)
    pf = {
        "holdings": [
            {"code": "002583", "shares": 400},
            {"code": "000725", "shares": 200},
        ]
    }
    (base / "portfolio.json").write_text(json.dumps(pf), encoding="utf-8")
    stale = {
        "code": "688008",
        "as_of": "2026-09-28T00:01:22+00:00",
        "portfolio": {"cash": 55733.96, "total": 103334.96},
    }
    (base / "last_morning.json").write_text(json.dumps(stale), encoding="utf-8")
    fresh = {
        "code": "002583",
        "baseline_saved_at": "2026-09-29T00:02:15+00:00",
        "portfolio": {"cash": 76958.79, "total": 102490.79, "holdings": pf["holdings"]},
    }
    (base / "baselines" / "morning" / "002583.json").write_text(json.dumps(fresh), encoding="utf-8")

    monkeypatch.setattr(
        "agent_reach.daily_run.workflows.morning_baseline_path",
        lambda code: base / "baselines" / "morning" / f"{code}.json",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.snapshot_builder.load_portfolio",
        lambda: pf,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 9, 29),
    )

    hit = _load_morning_baseline_from_holdings(session=date(2026, 9, 29))
    assert hit is not None
    assert hit["portfolio"]["cash"] == 76958.79

    loaded = load_morning_baseline()
    assert loaded["portfolio"]["cash"] == 76958.79


def test_load_morning_baseline_rejects_stale_legacy(tmp_path, monkeypatch):
    base = tmp_path / "daily_run"
    base.mkdir()
    stale = {
        "code": "688008",
        "as_of": "2026-09-28T00:01:22+00:00",
        "portfolio": {"cash": 55733.96},
    }
    legacy = base / "last_morning.json"
    legacy.write_text(json.dumps(stale), encoding="utf-8")

    monkeypatch.setattr("agent_reach.daily_run.workflows._default_baseline_path", lambda: legacy)
    monkeypatch.setattr(
        "agent_reach.daily_run.workflows._load_morning_baseline_from_holdings",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 9, 29),
    )

    with pytest.raises(FileNotFoundError, match="legacy 早盘基线日期"):
        load_morning_baseline()


def test_apply_portfolio_cash_reconcile_skips_large_drift():
    pf = {"cash": 78534.84, "total": 102094.84, "holdings": []}
    out, changed, note = apply_portfolio_cash_reconcile(
        pf,
        morning_cash=55733.96,
        ledger_trades=[],
        max_auto_correction=5000.0,
    )
    assert changed is False
    assert out["cash"] == 78534.84
    assert note and "跳过 cash reconcile" in note


def test_apply_portfolio_cash_reconcile_ok_for_ledger_aligned():
    pf = {"cash": 78540.0, "total": 102100.0, "holdings": []}
    ledger = [
        {
            "actions": [
                {"side": "sell", "shares": 200, "price": 7.89, "amount": 1578.0, "commission": 2.0}
            ]
        }
    ]
    out, changed, note = apply_portfolio_cash_reconcile(
        pf,
        morning_cash=76958.79,
        ledger_trades=ledger,
        tolerance=10.0,
    )
    assert changed is False
    assert out["cash"] == 78540.0
