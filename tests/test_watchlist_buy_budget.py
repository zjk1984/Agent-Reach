# -*- coding: utf-8
"""Watchlist vs holding buy budget precheck labeling."""

from agent_reach.daily_run.portfolio_manager import (
    ApplyResult,
    buy_budget_precheck_reason,
    render_apply_markdown,
    watchlist_candidate_affordable,
    watchlist_require_affordable_lot,
)


def test_watchlist_budget_reason_tagged(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.simulate_buy_analysis",
        lambda *a, **k: {
            "allowed": False,
            "block_reason": "688981 可部署买入预算 ¥11,753 不足一手",
        },
    )
    pf = {"holdings": [{"code": "688008", "shares": 100}]}
    reason = buy_budget_precheck_reason(
        pf,
        {},
        {"deploy_signal": {"watchlist_buy_precheck_only": True}},
        prefer_code="688981",
    )
    assert "观察池买入预算不足" in reason


def test_render_apply_markdown_watchlist_label():
    md = render_apply_markdown(
        ApplyResult(applied=False, portfolio={}, message="x"),
        decision={"block_kind": "buy_budget", "reasoning": "【观察池买入预算不足】688981"},
    )
    assert "观察池" in md
    assert "非现金不足" in md


def test_watchlist_candidate_affordable_respects_deploy_budget(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.watchlist_per_trade_budget",
        lambda *a, **k: {
            "per_budget": 15_000,
            "deploy_ratio": 0.25,
            "min_cash_ratio": 0.1,
            "commission_rate": 0.0015,
        },
    )
    pf = {"holdings": [], "watchlist": [], "cash": 50_000, "total": 100_000}
    enriched = {
        "688981": {"code": "688981", "name": "中芯国际", "price": 119.0},
        "000725": {"code": "000725", "name": "京东方A", "price": 5.75},
    }
    settings = {"watchlist": {"require_affordable_lot": True}}

    ok_exp, _ = watchlist_candidate_affordable(pf, enriched, settings, "688981")
    ok_cheap, _ = watchlist_candidate_affordable(pf, enriched, settings, "000725")
    assert ok_exp is False
    assert ok_cheap is True


def test_watchlist_require_affordable_lot_can_disable():
    assert watchlist_require_affordable_lot({"watchlist": {"require_affordable_lot": False}}) is False
