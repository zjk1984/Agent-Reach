# -*- coding: utf-8
"""Tests for TradingAgents-inspired TA patterns (reflection, debate, llm tier)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_reach.daily_run.job_checkpoint import JobCheckpoint
from agent_reach.daily_run.llm_tier import apply_llm_tier, resolve_job_tier
from agent_reach.daily_run.ta_patterns import (
    build_forecast_reflection_context,
    build_risk_debate_context,
    generate_decision_reflection,
    generate_invest_debate_narrative,
    generate_risk_debate_narrative,
    persist_decision_reflection,
)


def test_build_risk_debate_context_requires_conflicts():
    assert build_risk_debate_context({"team_review": {"conflicts": []}}) is None
    ctx = build_risk_debate_context(
        {
            "team_review": {"conflicts": ["tech vs risk"], "consensus_label": "分歧"},
            "expert_results": [
                {"name": "technical", "score": 70},
                {"name": "risk", "score": 40},
            ],
        }
    )
    assert ctx is not None
    assert ctx["conflicts"] == ["tech vs risk"]


def test_generate_decision_reflection_deterministic():
    with patch("agent_reach.daily_run.llm_chat.resolve_chat_provider", return_value=None):
        out = generate_decision_reflection(
            build_forecast_reflection_context(
                {
                    "week_start": "2026-09-08",
                    "week_end": "2026-09-12",
                    "symbols": {"688008": {"kronos": {"cum_change_pct": 1.2}}},
                    "notes": ["Kronos 偏多"],
                }
            ),
            settings={"decision_reflection": {"enabled": True, "planner": "deterministic"}},
        )
    assert out["planner"] == "deterministic"
    assert "预测反思" in out["summary"]
    assert out.get("reflection_prose")


def test_resolve_job_tier_defaults():
    assert resolve_job_tier("morning") == "tool"
    assert resolve_job_tier("decision_reflection") == "reasoning"
    assert resolve_job_tier(
        "risk_debate",
        settings={"llm_tier": {"job_tiers": {"risk_debate": "quick"}}},
    ) == "quick"


def test_apply_llm_tier_merges_deep_model():
    merged = apply_llm_tier(
        {"provider": "deepseek", "model": "old"},
        "invest_debate",
        settings={
            "llm_tier": {
                "enabled": True,
                "reasoning": {"provider": "deepseek", "model": "deep-model"},
            }
        },
    )
    assert merged["model"] == "deep-model"
    assert merged["llm_tier"] == "reasoning"
    assert merged["llm_role"] == "reasoning"


def test_generate_risk_debate_skips_without_conflicts():
    out = generate_risk_debate_narrative({"team_review": {"conflicts": []}})
    assert out.get("skipped") is True


def test_invest_debate_checkpoint_write(tmp_path, monkeypatch):
    ckpt = JobCheckpoint(job="invest_debate", scope_key="2026-09-08_2026-09-12", base_dir=tmp_path)
    monkeypatch.setattr(
        "agent_reach.daily_run.ta_patterns._invest_debate_checkpoint",
        lambda scope_key, settings=None: ckpt,
    )
    with patch("agent_reach.daily_run.llm_chat.resolve_chat_provider", return_value=None):
        out = generate_invest_debate_narrative(
            {
                "job": "invest_debate",
                "scope": "weekly",
                "scope_key": "2026-09-08_2026-09-12",
                "week_start": "2026-09-08",
                "week_end": "2026-09-12",
                "hot_sectors": [{"name": "半导体", "reason": "景气回升"}],
            },
            settings={"invest_debate": {"enabled": True, "planner": "deterministic", "checkpoint": True}},
        )
    assert out.get("skipped") is not True
    loaded = ckpt.load()
    assert loaded["scope_key"] == "2026-09-08_2026-09-12"
    assert loaded.get("summary")


def test_persist_decision_reflection_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_reach.daily_run.experience.experience_dir", lambda: tmp_path)
    fragment = tmp_path.parent / "skill" / "experience_latest.md"
    monkeypatch.setattr(
        "agent_reach.daily_run.ta_patterns.Path.home",
        lambda: tmp_path.parent,
    )
    result = persist_decision_reflection(
        {
            "reflection_prose": "测试反思 prose",
            "planner": "deterministic",
            "focus_points": ["A"],
        },
        job_scope="close",
        settings={"decision_reflection": {"persist_experience": True}},
    )
    assert result.get("ok") is True
    line = (tmp_path / "experience.jsonl").read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["kind"] == "decision_reflection"
    assert "测试反思" in entry["prose"]


@patch("agent_reach.daily_run.llm_chat.resolve_chat_provider", return_value="deepseek")
def test_chat_json_retries_on_failure(mock_provider):
    from agent_reach.daily_run.llm_chat import chat_json

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": '{"summary":"ok","focus_points":[]}'}}]}
    ).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", side_effect=[OSError("fail"), mock_resp]) as mock_open:
        payload = chat_json(
            system="test",
            user="{}",
            provider="deepseek",
            max_retries=2,
        )
    assert payload is not None
    assert payload["summary"] == "ok"
    assert mock_open.call_count == 2
