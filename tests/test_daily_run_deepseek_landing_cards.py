# -*- coding: utf-8
"""Tests for DeepSeek landing transparency cards."""

from agent_reach.daily_run.deepseek_landing_cards import (
    append_deepseek_landing_report_section,
    build_deepseek_landing_snapshot,
    deepseek_landing_card_enabled,
    render_deepseek_landing_markdown,
)
from agent_reach.daily_run.report_push import ReportSection


def test_deepseek_landing_card_enabled_default():
    assert deepseek_landing_card_enabled({"report": {}}) is True
    assert deepseek_landing_card_enabled({"report": {"deepseek_landing_card": {"enabled": False}}}) is False


def test_render_markdown_has_active_and_suitable_sections():
    settings = {
        "report": {"deepseek_landing_card": {"enabled": True}},
        "llm_narrative": {
            "enabled": True,
            "planner": "llm",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "jobs": {"morning": True, "midday": {"planner": "deterministic"}},
        },
        "harness_evolution": {"llm_optimize": True},
        "sell_rules_whatif": {"llm_optimize": True},
    }
    md = render_deepseek_landing_markdown(
        "morning",
        settings=settings,
        runtime={"narrative": {"planner": "llm", "summary": "test"}},
    )
    assert "DeepSeek 引入场景与落地点" in md
    assert "计算用代码，解读用模型" in md
    assert "解读类" in md
    assert "规则解读" in md


def test_append_report_section_renumbers():
    sections = [
        ReportSection(category="decision", title="", body="body"),
    ]

    def renumber(cards):
        total = len(cards)
        for i, sec in enumerate(cards, start=1):
            sec.title = f"{sec.category} {i}/{total}"

    out = append_deepseek_landing_report_section(
        sections,
        report_kind="midday",
        settings={"report": {}, "midday": {"llm_narrative": {"enabled": True, "planner": "deterministic"}}},
        runtime={},
        renumber=renumber,
    )
    assert len(out) >= 2
    assert out[-1].category == "deepseek_landing"
    assert "/2" in out[-1].title or "/3" in out[-1].title


def test_narrative_system_prompt_includes_deepseek_rule():
    from agent_reach.daily_run.report_narrative import _NARRATIVE_LIMITS_DEFAULT, _narrative_system_prompt

    prompt = _narrative_system_prompt("morning", limits=_NARRATIVE_LIMITS_DEFAULT)
    assert "不得推算、修改或新增价格" in prompt
    assert "不得给出新的买卖价位" in prompt


def test_build_snapshot_filters_by_report_kind():
    settings = {
        "llm_narrative": {"enabled": True, "planner": "deterministic", "jobs": {"forecast": True}},
        "harness_evolution": {"llm_optimize": True},
        "forecast_calibration": {"llm_optimize": True},
    }
    snap = build_deepseek_landing_snapshot("forecast", settings=settings, runtime={})
    ids = {row["id"] for row in (snap.get("active") or []) + (snap.get("suitable") or [])}
    assert "forecast_calibrate" in ids
    assert "sell_rules_whatif" not in ids
