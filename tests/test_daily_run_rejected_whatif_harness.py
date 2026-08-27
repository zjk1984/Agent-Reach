# -*- coding: utf-8
"""Tests for rejected weekly_whatif harness refinement."""

from unittest.mock import patch

from agent_reach.daily_run.rejected_whatif_harness import (
    apply_weekly_rejected_whatif_harness_refinement,
    weekly_rejected_refresh_to_harness_evidence,
)


def test_weekly_rejected_refresh_evidence_flags_profit_week_adds():
    report = {
        "weekly_pnl_pct": 0.5,
        "sell_rules_whatif": {"skipped": True},
        "buy_rules_whatif": {"skipped": True},
    }
    refresh = {"added": ["禁止接飞刀追涨"], "archived": 1}
    with patch(
        "agent_reach.daily_run.skill_rejected._candidates_from_weekly_report",
        return_value=[("禁止接飞刀追涨", "x")],
    ):
        evidence = weekly_rejected_refresh_to_harness_evidence(
            report,
            refresh_result=refresh,
            settings={"rejected_strategies": {"weekly_whatif": {"mode": "harness"}}},
        )
    assert any("盈利周证伪库仍入库" in p for p in evidence["policy"])


@patch("agent_reach.daily_run.rejected_whatif_harness.optimize_weekly_whatif_with_deepseek")
@patch("agent_reach.daily_run.rejected_whatif_harness.apply_skill_refinement")
def test_apply_weekly_rejected_whatif_skips_when_disabled(mock_refine, mock_llm):
    mock_llm.return_value = {"skipped": True, "reason": "no llm"}
    mock_refine.return_value = {"changes": 1}
    out = apply_weekly_rejected_whatif_harness_refinement(
        {"weekly_pnl_pct": -1.0},
        refresh_result={"added": []},
        settings={"rejected_strategies": {"weekly_whatif": {"mode": "fixed"}}},
    )
    assert out.get("skipped") is True
    mock_refine.assert_not_called()
