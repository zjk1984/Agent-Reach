# -*- coding: utf-8
"""Tests for Feishu Executive block (Tier A)."""

from unittest.mock import patch

from agent_reach.daily_run.executive_block import (
    build_executive_context,
    executive_block_enabled,
    format_executive_block,
    prepend_executive_block,
)
from agent_reach.daily_run.report_push import ReportSection, push_report_sections
from agent_reach.daily_run.settings import load_settings


def test_executive_block_enabled_default_on():
    assert executive_block_enabled({})
    assert executive_block_enabled({"report": {"card_tier": {"executive_enabled": True}}})
    assert not executive_block_enabled({"report": {"card_tier": {"executive_enabled": False}}})


def test_format_executive_block_close_shape():
    ctx = build_executive_context(
        "close",
        portfolio_summary={"daily_pnl": 12300, "daily_pnl_pct": 0.41, "cash_ratio": 0.2},
        primary_report={
            "name": "澜起科技",
            "code": "688008",
            "mss_current": 62,
            "verdict_current": "可做",
        },
        decision_closure_line="**执行/gate:** · hold · gate=OK · ledger —",
        as_of="2026-11-21",
    )
    settings = load_settings()
    md = format_executive_block(
        report_type="verify",
        settings=settings,
        context=ctx,
        split=True,
        section_count=8,
    )
    assert "**📌 Executive**" in md
    assert "job=close" in md
    assert "push=split/8" in md
    assert "PnL:" in md and "+¥12,300" in md
    assert "688008" in md
    assert "**gate:**" in md
    assert "**执行/gate:**" in md
    assert "**异常:** 无" in md


@patch("agent_reach.integrations.feishu.send_card")
def test_push_report_sections_prepends_executive(mock_send):
    mock_send.return_value = {"code": 0}
    settings = load_settings()
    settings.setdefault("report", {})["split_push_interval_seconds"] = 0
    ctx = build_executive_context(
        "morning",
        settings=settings,
        primary_report={"name": "测试", "code": "000001", "mss_final": 50, "verdict": "观察"},
    )
    sections = [
        ReportSection(category="decision", title="t1", body="正文 A"),
        ReportSection(category="experts", title="t2", body="正文 B"),
    ]
    push_report_sections(
        sections,
        settings=settings,
        config=None,
        report_type="premarket",
        fallback_title="test",
        split=True,
        executive_context=ctx,
    )
    first_body = mock_send.call_args_list[0][0][2]
    assert "**📌 Executive**" in first_body
    assert "job=morning" in first_body
    assert "正文 A" in first_body
    assert mock_send.call_count == 2


def test_prepend_executive_respects_disable_flag():
    settings = {"report": {"card_tier": {"executive_enabled": False}}}
    ctx = build_executive_context("intraday", primary_report={"code": "1"})
    out = prepend_executive_block("body", report_type="intraday", settings=settings, context=ctx)
    assert out == "body"