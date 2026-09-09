# -*- coding: utf-8
"""Tests for ai-berkshire roadmap integrations."""

from unittest.mock import patch

from agent_reach.daily_run.berkshire.investment_checklist import evaluate_investment_checklist
from agent_reach.daily_run.berkshire.news_pulse import (
    collect_news_pulse_targets,
    render_news_pulse_markdown,
)
from agent_reach.daily_run.berkshire.portfolio_review import review_portfolio
from agent_reach.daily_run.berkshire.report_audit import audit_card_context, render_report_audit_markdown


def test_report_audit_warns_missing_as_of():
    audit = audit_card_context(snapshot={}, settings={"berkshire": {"report_audit": {"enabled": True}}})
    assert audit["passed"] is False
    assert any("as_of" in w for w in audit["warnings"])
    md = render_report_audit_markdown(audit)
    assert "report_audit" in md


def test_collect_news_pulse_targets_from_drawdown():
    portfolio = {
        "watchlist": [
            {"code": "002415", "name": "海康威视", "change_pct": -4.0, "day_low": 28.0, "prev_close": 30.0},
        ]
    }
    settings = {
        "berkshire": {"news_pulse": {"enabled": True, "min_severity": "yellow"}},
        "intraday": {"watchlist_drawdown": {"mode": "fixed", "yellow_pct": -3.0, "red_pct": -5.0}},
    }
    targets = collect_news_pulse_targets(portfolio, settings=settings)
    assert len(targets) >= 1


@patch("agent_reach.daily_run.berkshire.news_pulse._fetch_eastmoney", return_value=[{"title": "业绩预警"}])
@patch("agent_reach.daily_run.berkshire.news_pulse._fetch_exa", return_value=[])
def test_render_news_pulse_markdown(_mock_exa, _mock_em):
    from agent_reach.daily_run.berkshire.news_pulse import run_news_pulse_lite

    row = run_news_pulse_lite(
        {
            "code": "002415",
            "name": "海康威视",
            "severity": "red",
            "text": "海康威视 日内最深 -6%",
        },
        settings={"berkshire": {"news_pulse": {"enabled": True}}},
    )
    md = render_news_pulse_markdown([row])
    assert "新闻脉搏" in md
    assert "论文重审" in md


def test_investment_checklist_blocks_on_grade_c():
    snapshot = {"price": 10.0, "mss_breakdown": {"fx": 50}}
    checklist = evaluate_investment_checklist(
        snapshot,
        settings={"berkshire": {"investment_checklist": {"enabled": True}}},
    )
    assert checklist.get("block_buy") is True
    assert checklist.get("reasons")


def test_portfolio_review_concentration_warning():
    review = review_portfolio(
        {
            "holdings": [
                {"code": "600519", "name": "茅台", "shares": 100, "price": 100.0},
                {"code": "000001", "name": "平安", "shares": 10, "price": 10.0},
            ],
            "watchlist": [],
        },
        settings={"berkshire": {"portfolio_review": {"enabled": True, "max_single_position_pct": 50}}},
    )
    assert review["passed"] is False
    assert review["warnings"]
