# -*- coding: utf-8
"""Tests for DeepEar P0: ISQ-lite, thesis evolution, llm tier roles, job checkpoint."""

import json

import pytest

from agent_reach.daily_run.isq_lite import (
    enrich_hot_topic_diff,
    enrich_hot_sectors,
    score_hot_topic_item,
)
from agent_reach.daily_run.job_checkpoint import JobCheckpoint
from agent_reach.daily_run.llm_tier import apply_llm_tier, resolve_job_role, resolve_job_tier
from agent_reach.daily_run.thesis_evolution import (
    build_weekly_thesis_snapshot,
    compute_thesis_diff,
    persist_thesis_evolution,
    render_thesis_diff_markdown,
)


def test_isq_dual_source_scores_higher():
    single = score_hot_topic_item({"title": "半导体政策", "platform": "60s"})
    dual = score_hot_topic_item({"title": "半导体政策", "platform": "60s"}, dual_source=True)
    assert dual["isq_composite"] > single["isq_composite"]
    assert dual["isq"]["confidence"] > single["isq"]["confidence"]


def test_enrich_hot_topic_diff_adds_isq():
    diff = enrich_hot_topic_diff(
        {
            "overlap_count": 1,
            "overlap": [{"title": "AI 算力", "platform": "60s"}],
            "only_60s": [],
            "only_redfox": [],
        },
        settings={"isq_lite": {"enabled": True}},
    )
    assert diff["overlap"][0]["isq_composite"] is not None
    assert diff.get("isq_overlap_mean") is not None


def test_enrich_hot_sectors_adds_isq():
    rows = enrich_hot_sectors(
        [{"code": "688008", "name": "澜起", "change_pct": 3.2, "sector": "半导体"}],
        settings={"isq_lite": {"enabled": True}},
    )
    assert rows[0]["isq"]["transmission"] >= 0.7


def test_resolve_job_role_and_reasoning_tier():
    assert resolve_job_role("weekly") == "reasoning"
    assert resolve_job_role("counter_thesis_llm") == "tool"
    assert resolve_job_tier("weekly") == "reasoning"
    assert resolve_job_tier("counter_thesis_llm") == "tool"


def test_apply_llm_tier_sets_role():
    merged = apply_llm_tier({}, "forecast", settings={"llm_tier": {"enabled": True}})
    assert merged["llm_role"] == "reasoning"
    assert merged["llm_tier"] == "reasoning"


def test_job_checkpoint_atomic_save(tmp_path):
    ckpt = JobCheckpoint(job="demo", scope_key="2026-09-08", base_dir=tmp_path)
    ckpt.save({"hello": "world"})
    loaded = ckpt.load()
    assert loaded["hello"] == "world"
    assert ckpt.path.exists()


def test_thesis_diff_detects_theme_change():
    prior = build_weekly_thesis_snapshot(
        {
            "week_start": "2026-09-01",
            "week_end": "2026-09-05",
            "hot_sectors": [{"sector": "半导体", "code": "688008", "name": "澜起"}],
            "llm_narrative": {"summary": "旧叙事"},
            "hot_topic_diff": {"overlap_count": 1},
        }
    )
    current = build_weekly_thesis_snapshot(
        {
            "week_start": "2026-09-08",
            "week_end": "2026-09-12",
            "hot_sectors": [{"sector": "新能源", "code": "300750", "name": "宁德"}],
            "llm_narrative": {"summary": "新叙事"},
            "hot_topic_diff": {"overlap_count": 3},
        }
    )
    diff = compute_thesis_diff(current, prior)
    assert diff["has_prior"] is True
    assert "新能源" in diff["themes_added"]
    assert "半导体" in diff["themes_removed"]
    assert diff["narrative_changed"] is True
    assert diff["overlap_delta"] == 2


def test_persist_thesis_evolution_writes_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.thesis_evolution.JobCheckpoint.for_job",
        lambda job, scope_key, settings=None: JobCheckpoint(job=job, scope_key=scope_key, base_dir=tmp_path),
    )
    first = persist_thesis_evolution(
        build_weekly_thesis_snapshot(
            {
                "week_start": "2026-09-01",
                "week_end": "2026-09-05",
                "hot_sectors": [{"sector": "半导体"}],
                "llm_narrative": {"summary": "A"},
                "hot_topic_diff": {},
            }
        ),
        settings={"thesis_evolution": {"enabled": True}, "job_checkpoint": {"enabled": True}},
    )
    assert first.get("diff", {}).get("has_prior") is False

    second = persist_thesis_evolution(
        build_weekly_thesis_snapshot(
            {
                "week_start": "2026-09-08",
                "week_end": "2026-09-12",
                "hot_sectors": [{"sector": "AI"}],
                "llm_narrative": {"summary": "B"},
                "hot_topic_diff": {"overlap_count": 2},
            }
        ),
        settings={"thesis_evolution": {"enabled": True}, "job_checkpoint": {"enabled": True}},
    )
    diff = second.get("diff") or {}
    assert diff.get("has_prior") is True
    assert "AI" in (diff.get("themes_added") or [])


def test_render_thesis_diff_markdown():
    md = render_thesis_diff_markdown(
        {
            "has_prior": True,
            "prior_week_start": "2026-09-01",
            "prior_week_end": "2026-09-05",
            "week_start": "2026-09-08",
            "week_end": "2026-09-12",
            "themes_added": ["AI"],
            "themes_removed": ["半导体"],
            "themes_kept": [],
            "narrative_changed": True,
            "overlap_delta": 1,
            "drift_score": 3,
        }
    )
    assert "逻辑演变" in md
    assert "AI" in md
