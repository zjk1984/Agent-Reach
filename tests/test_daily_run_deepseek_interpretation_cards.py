# -*- coding: utf-8
"""Tests for DeepSeek interpretation cards."""

from agent_reach.daily_run.deepseek_interpretation_cards import (
    DEEPSEEK_USAGE_PRINCIPLE,
    append_interpretation_report_section,
    interpretation_card_enabled,
    render_deepseek_interpretation_markdown,
)
from agent_reach.daily_run.report_push import ReportSection


def test_interpretation_card_enabled_default():
    assert interpretation_card_enabled({"report": {}}) is True
    assert interpretation_card_enabled({"report": {"deepseek_interpretation_card": {"enabled": False}}}) is False


def test_render_markdown_llm_includes_principle():
    narrative = {
        "planner": "llm",
        "summary": "测试摘要",
        "focus_points": ["要点A"],
        "job": "morning",
    }
    md = render_deepseek_interpretation_markdown(
        narrative,
        job="morning",
        settings={"report": {"deepseek_interpretation_card": {"enabled": True}}},
    )
    assert DEEPSEEK_USAGE_PRINCIPLE in md
    assert "DeepSeek 解读" in md
    assert "测试摘要" in md


def test_render_markdown_skips_intraday():
    narrative = {"planner": "llm", "summary": "盘中", "job": "intraday"}
    md = render_deepseek_interpretation_markdown(narrative, job="intraday", settings={})
    assert md == ""


def test_render_markdown_deterministic_no_principle_header():
    narrative = {
        "planner": "deterministic",
        "summary": "规则摘要",
        "focus_points": ["B"],
        "job": "close",
    }
    md = render_deepseek_interpretation_markdown(narrative, job="close", settings={})
    assert "规则解读" in md
    assert DEEPSEEK_USAGE_PRINCIPLE not in md


def test_append_report_section_renumbers():
    sections = [
        ReportSection(category="decision", title="", body="body"),
    ]

    def renumber(cards):
        total = len(cards)
        for i, sec in enumerate(cards, start=1):
            sec.title = f"{sec.category} {i}/{total}"

    out = append_interpretation_report_section(
        sections,
        {"planner": "llm", "summary": "midday", "focus_points": ["x"], "job": "midday"},
        job="midday",
        settings={"report": {}},
        renumber=renumber,
    )
    assert len(out) == 2
    assert out[-1].category == "deepseek_interpretation"
    assert "/2" in out[-1].title


def test_narrative_system_prompt_includes_deepseek_rule():
    from agent_reach.daily_run.report_narrative import _NARRATIVE_LIMITS_DEFAULT, _narrative_system_prompt

    prompt = _narrative_system_prompt("morning", limits=_NARRATIVE_LIMITS_DEFAULT)
    assert "不得推算、修改或新增价格" in prompt
    assert "不得给出新的买卖价位" in prompt
