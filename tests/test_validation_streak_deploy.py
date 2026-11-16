# -*- coding: utf-8
"""AR-29 — validation streak deploy tighten via harness overlay."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.daily_run.forecast_validation_harness import (
    build_deploy_tighten_signal,
    persist_forecast_validation_closure,
)
from agent_reach.daily_run.harness_policy import resolve_harness_position_policy
from agent_reach.daily_run.harness import HarnessState
from agent_reach.daily_run import validation_streak_deploy as vsd
from agent_reach.daily_run.validation_streak_deploy import (
    apply_validation_streak_deploy_to_merged,
    compute_validation_streak_deploy_cap,
    load_validation_streak_deploy_state,
    maybe_apply_validation_streak_deploy_tighten,
)
from agent_reach.daily_run.storage import reset_store


@pytest.fixture
def streak_env(tmp_path, monkeypatch):
    reports = tmp_path / "reports" / "forecast_validation"
    reports.mkdir(parents=True)
    harness = tmp_path / "harness_state"
    harness.mkdir(parents=True, exist_ok=True)
    audit = harness / "apply_audit.jsonl"
    monkeypatch.setattr(
        "agent_reach.daily_run.forecast_validation_harness.validation_reports_dir",
        lambda: reports,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.validation_streak_deploy.validation_streak_deploy_state_path",
        lambda: harness / "validation_streak_deploy.json",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_apply_gate._audit_path",
        lambda: audit,
    )
    db_path = tmp_path / "daily_run.db"
    settings = {
        "position": {"deploy_ratio": 0.55},
        "harness": {
            "runtime_overlay": True,
            "threshold_evolution_mode": "harness",
            "threshold_modes": {"deploy_ratio": "fixed"},
        },
        "week_forecast": {
            "validation_harness": {
                "enabled": True,
                "index_miss_streak_warn": 2,
                "benchmark_underperform_streak_warn": 2,
                "auto_tighten_deploy_on_streak": True,
                "deploy_step_per_week": 0.05,
                "deploy_floor": 0.15,
            }
        },
        "storage": {
            "enabled": True,
            "backend": "sqlite",
            "sqlite_path": str(db_path),
        },
    }
    monkeypatch.setenv("AGENT_REACH_STORAGE", "1")
    reset_store()
    yield {"settings": settings, "harness": harness, "audit": audit}
    reset_store()


def _active_signal() -> dict:
    return {
        "active": True,
        "index_miss_streak": 3,
        "benchmark_underperform_week_streak": 0,
        "index_miss_streak_warn": 2,
        "benchmark_streak_warn": 2,
        "reasons": ["指数预测区间连续未命中 3 周"],
    }


def test_compute_cap_steps_down_and_floors(streak_env):
    settings = streak_env["settings"]
    cap = compute_validation_streak_deploy_cap(_active_signal(), settings=settings)
    assert cap["deploy_cap"] == pytest.approx(0.45)
    assert cap["penalty_weeks"] == 2


def test_maybe_apply_writes_state_and_audit(streak_env):
    settings = streak_env["settings"]
    record = {"week_start": "2026-08-04", "week_end": "2026-08-08"}
    signal = _active_signal()
    out = maybe_apply_validation_streak_deploy_tighten(record, signal, settings=settings)
    assert out["changed"] is True
    assert out["deploy_cap"] == pytest.approx(0.45)
    state = load_validation_streak_deploy_state()
    assert state["deploy_cap"] == pytest.approx(0.45)
    assert streak_env["audit"].exists()
    lines = streak_env["audit"].read_text(encoding="utf-8").strip().splitlines()
    audit = json.loads(lines[-1])
    assert audit["reason"] == "validation_streak_deploy_tighten"
    assert out["feishu_line"]


def test_overlay_caps_merged_deploy(streak_env):
    settings = streak_env["settings"]
    maybe_apply_validation_streak_deploy_tighten(
        {"week_start": "2026-08-04"},
        _active_signal(),
        settings=settings,
    )
    merged = {"deploy_ratio": 0.8, "max_position_pct": 35.0}
    capped = apply_validation_streak_deploy_to_merged(merged, settings=settings)
    assert capped["deploy_ratio"] == pytest.approx(0.45)

    state = HarnessState()
    eff = resolve_harness_position_policy(state, settings=settings)
    assert eff["deploy_ratio"] <= 0.45 + 1e-6


def test_release_when_streak_clears(streak_env):
    settings = streak_env["settings"]
    path = vsd.validation_streak_deploy_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "deploy_cap": 0.45,
                "base_deploy": 0.55,
                "overlay_active": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cleared = {"active": False, "index_miss_streak": 0, "benchmark_underperform_week_streak": 0}
    cap = compute_validation_streak_deploy_cap(cleared, settings=settings)
    assert cap["deploy_cap"] == pytest.approx(0.50)


def test_persist_applies_when_auto_enabled(streak_env):
    settings = streak_env["settings"]
    verification = {
        "week_start": "2026-08-04",
        "week_end": "2026-08-08",
        "rows": [{"prediction": "大盘", "hit": False}],
        "metrics": {},
    }
    forecast = {
        "week_start": "2026-08-04",
        "structured_predictions": {"market": {"change_pct_low": 0, "change_pct_high": 1}},
    }
    with patch(
        "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
        return_value={"ok": True, "return_pct": 0.0},
    ), patch(
        "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
        return_value={"underperform_week_streak": 0},
    ), patch(
        "agent_reach.daily_run.forecast_validation_harness.compute_index_band_miss_streak",
        return_value=3,
    ), patch(
        "agent_reach.daily_run.forecast_validation_harness.build_compact_validation_record",
        return_value={
            "week_start": "2026-08-04",
            "index": {"band_hit": False},
            "benchmark_underperform": {},
        },
    ):
        out = persist_forecast_validation_closure(verification, forecast, settings=settings)
    assert out["deploy_tighten"].get("changed") is True
    assert load_validation_streak_deploy_state()["deploy_cap"] == pytest.approx(0.45)