# -*- coding: utf-8
"""Tests for daily-run ops ledger-reconcile (AR-6)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent_reach.daily_run.ledger_reconcile import (
    gather_cost_marks,
    render_ledger_reconcile_markdown,
    replay_holdings_from_ledger,
    run_ledger_reconcile,
)


def test_replay_holdings_buy_sell_fifo():
    trades = [
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
    ]
    seed = [{"code": "002583", "shares": 0, "cost": 12.618}]
    out = replay_holdings_from_ledger(trades, seed_holdings=seed)
    assert out["002583"]["shares"] == 1000
    assert out["002583"]["avg_cost"] == pytest.approx(8.012, abs=0.01)


def test_run_ledger_reconcile_portfolio_matches(tmp_path, monkeypatch):
    ledger = tmp_path / "trade_ledger.jsonl"
    portfolio = tmp_path / "portfolio.json"
    morning = tmp_path / "last_morning.json"

    ledger.write_text(
        json.dumps(
            {
                "at": "2026-10-22T01:50:00+00:00",
                "actions": [
                    {
                        "side": "buy",
                        "code": "000725",
                        "name": "京东方A",
                        "shares": 200,
                        "price": 5.95,
                        "amount": 1190.0,
                        "commission": 5.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    portfolio.write_text(
        json.dumps(
            {
                "cash": 48805.0,
                "holdings": [
                    {"code": "000725", "name": "京东方A", "shares": 500, "cost": 5.95, "price": 5.71},
                ],
                "trade_session_date": "2026-10-23",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    morning.write_text(
        json.dumps(
            {
                "portfolio": {
                    "cash": 50000.0,
                    "holdings": [
                        {"code": "000725", "name": "京东方A", "shares": 300, "cost": 6.0},
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _fake_morning():
        return json.loads(morning.read_text(encoding="utf-8"))

    monkeypatch.setattr("agent_reach.daily_run.ledger_reconcile._load_seed_portfolio", lambda _s: (
        _fake_morning()["portfolio"]["holdings"],
        "test_morning",
        float(_fake_morning()["portfolio"]["cash"]),
    ))

    result = run_ledger_reconcile(
        as_of=date(2026, 10, 23),
        ledger_path=ledger,
        portfolio_path=portfolio,
        focus_codes=["000725"],
        mark_dates=[date(2026, 10, 23)],
    )
    row = next(h for h in result.holdings if h.code == "000725")
    assert row.shares_match is True
    assert row.ledger_shares == 500
    md = render_ledger_reconcile_markdown(result)
    assert "000725" in md
    assert "持仓：portfolio vs ledger" in md


def test_gather_cost_marks_flags_cost_equals_price():
    pf = {
        "trade_session_date": "2026-10-23",
        "holdings": [
            {
                "code": "002583",
                "name": "海能达",
                "shares": 1000,
                "cost": 12.618,
                "price": 12.618,
                "quote_source": "cost_fallback",
            }
        ],
    }
    rows = gather_cost_marks(pf, codes=["002583"], mark_days=[date(2026, 10, 23)])
    assert rows[0].cost_equals_price is True
    assert rows[0].cost_fallback is True
    assert rows[0].mark_price is None


def test_ops_cli_dry_run_rejects_apply(tmp_path, capsys):
    from argparse import Namespace

    from agent_reach.daily_run import ops_cli

    with pytest.raises(SystemExit) as exc:
        ops_cli.cmd_ops(
            Namespace(
                ops_action="ledger-reconcile",
                as_of="",
                ledger="",
                portfolio="",
                focus="002583",
                mark_dates="2026-10-23",
                json=False,
                apply=True,
            )
        )
    assert exc.value.code == 2