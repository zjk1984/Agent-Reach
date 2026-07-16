# -*- coding: utf-8
"""Tests for morning + S2 scan merge."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agent_reach.daily_run.intraday import record_scan, record_scan_from_evaluation, reset_state
from agent_reach.daily_run.settings import load_settings


@pytest.fixture
def evaluation():
    from agent_reach.daily_run.auditor import AuditResult
    from agent_reach.daily_run.quality_gate import GateResult
    from agent_reach.daily_run.verdict import VerdictResult

    return {
        "audit": AuditResult(passed=True, issues=[], warnings=[]),
        "gate": GateResult(passed=True, missing_fields=[], warnings=[], downgraded=False),
        "verdict": VerdictResult(
            verdict="观察",
            confidence="低",
            mss_final=48.47,
            entry_price=247.15,
            stop_loss_price=None,
            invalidation="test",
            reasoning="test",
            downgrade_reasons=[],
            blocked=False,
            label_key="watch",
        ),
        "report": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "code": "688008",
            "name": "2026-07-08 早盘",
            "mss_final": 48.47,
            "mss_breakdown": {"fx": 47.5},
            "verdict": "观察",
            "confidence": "低",
        },
    }


class TestMorningScanMerge:
    def test_record_scan_from_evaluation(self, evaluation, tmp_path):
        state_path = tmp_path / "state.json"
        reset_state(state_path)
        enriched = {"code": "688008", "price": 247.15, "report_type": "premarket"}
        result = record_scan_from_evaluation(
            enriched,
            evaluation,
            settings=load_settings(),
            state_path=state_path,
            source="morning",
        )
        assert result["scan"]["scan_id"] == "S1"
        assert result["scan"]["source"] == "morning"
        assert result["scan"]["mss_final"] == 48.47

    def test_record_scan_reuses_evaluation(self, evaluation, tmp_path):
        state_path = tmp_path / "state.json"
        reset_state(state_path)
        enriched = {"code": "688008", "price": 247.15}
        result = record_scan_from_evaluation(
            enriched,
            evaluation,
            settings=load_settings(),
            state_path=state_path,
            source="morning",
        )
        assert result["scan"]["scan_id"] == "S1"
