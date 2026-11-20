# -*- coding: utf-8
"""AR-7: ledger vs portfolio PnL dual-read (harness_finance + close/feishu paths)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent_reach.daily_run.finance_close_harness import finance_close_to_harness_evidence
from agent_reach.daily_run.finance_variance_harness import finance_variance_to_harness_evidence
from agent_reach.daily_run.harness_finance import (
    analyze_ledger_portfolio_pnl_dual_read,
    run_finance_close_checks,
)


def test_dual_read_warns_on_cost_mark_mismatch():
    portfolio = {
        "as_of": "2026-10-23",
        "holdings": [
            {"code": "002583", "shares": 1000, "cost": 12.618, "price": 8.08},
        ],
        "trades": [
            {
                "at": "2026-10-20T02:00:00+00:00",
                "actions": [
                    {
                        "side": "buy",
                        "code": "002583",
                        "shares": 1000,
                        "amount": 8000.0,
                        "commission": 12.0,
                        "price": 8.0,
                    }
                ],
            }
        ],
        "realized_pnl": 0.0,
    }
    seed = [{"code": "002583", "shares": 0, "cost": 12.618}]
    result = analyze_ledger_portfolio_pnl_dual_read(
        portfolio,
        seed_holdings=seed,
        settings={"ledger_reconcile": {"pnl_tolerance_cny": 1.0, "pnl_materiality_cny": 100.0}},
    )
    assert result.skipped is False
    assert result.within_tolerance is False
    assert result.material is True
    assert any("双读" in f for f in result.flags)


def test_dual_read_passes_when_costs_align():
    portfolio = {
        "as_of": "2026-10-23",
        "holdings": [{"code": "000725", "shares": 500, "cost": 5.96, "price": 5.71}],
        "trades": [
            {
                "at": "2026-10-22T01:50:00+00:00",
                "actions": [
                    {
                        "side": "buy",
                        "code": "000725",
                        "shares": 200,
                        "price": 5.95,
                        "amount": 1190.0,
                        "commission": 5.0,
                    }
                ],
            }
        ],
    }
    seed = [{"code": "000725", "shares": 300, "cost": 6.0}]
    result = analyze_ledger_portfolio_pnl_dual_read(
        portfolio,
        seed_holdings=seed,
        settings={"ledger_reconcile": {"pnl_tolerance_cny": 50.0}},
    )
    assert result.within_tolerance is True
    assert not result.flags


def test_finance_close_checks_surface_dual_read(tmp_path, monkeypatch):
    ledger = tmp_path / "trade_ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "at": "2026-10-22T01:50:00+00:00",
                "actions": [
                    {
                        "side": "buy",
                        "code": "002583",
                        "shares": 1000,
                        "price": 8.0,
                        "amount": 8000.0,
                        "commission": 12.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    pf = {
        "as_of": "2026-10-23",
        "start_total": 100000.0,
        "end_total": 100500.0,
        "daily_pnl": 500.0,
        "holdings": [{"code": "002583", "shares": 1000, "cost": 12.618, "price": 8.08}],
        "trades": [json.loads(ledger.read_text(encoding="utf-8").strip())],
    }
    monkeypatch.setattr(
        "agent_reach.daily_run.ledger_reconcile._load_seed_portfolio",
        lambda _s: ([{"code": "002583", "shares": 0, "cost": 12.618}], "test", 50000.0),
    )
    checks = run_finance_close_checks(
        pf,
        settings={"ledger_reconcile": {"pnl_tolerance_cny": 1.0, "pnl_materiality_cny": 100.0}},
    )
    dual = checks.get("ledger_pnl_dual") or {}
    assert dual.get("flags")
    evidence = finance_close_to_harness_evidence(checks, portfolio_summary=pf)
    assert any("双读" in m for m in evidence.get("memory") or [])


def test_finance_variance_evidence_includes_dual_read():
    report = {
        "week_end": "2026-10-23",
        "holdings": [{"code": "002583", "shares": 1000, "cost": 12.618, "price": 8.08}],
        "trades": [],
    }
    dual = analyze_ledger_portfolio_pnl_dual_read(
        {"as_of": "2026-10-23", **report},
        seed_holdings=[{"code": "002583", "shares": 1000, "cost": 8.012}],
        settings={"ledger_reconcile": {"pnl_tolerance_cny": 1.0}},
    )
    evidence = finance_variance_to_harness_evidence(
        report,
        {"reconciled": True, "total_variance": 0, "residual": 0},
        ledger_pnl_dual=dual.to_dict(),
    )
    if dual.flags:
        assert any("双读" in m for m in evidence.get("memory") or [])