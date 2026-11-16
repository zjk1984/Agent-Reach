# -*- coding: utf-8
"""Forecast validation harness — persistence, summary fields, harness signal."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.daily_run.forecast_validation_harness import (
    build_compact_validation_record,
    build_deploy_tighten_signal,
    compute_index_band_miss_streak,
    index_band_miss_streak,
    load_validation_index,
    persist_forecast_validation_closure,
    validation_index_path,
    validation_reports_dir,
)
from agent_reach.daily_run.storage import get_store, reset_store


@pytest.fixture
def validation_env(tmp_path, monkeypatch):
    reports = tmp_path / "reports" / "forecast_validation"
    reports.mkdir(parents=True)
    monkeypatch.setattr(
        "agent_reach.daily_run.forecast_validation_harness.validation_reports_dir",
        lambda: reports,
    )
    db_path = tmp_path / "daily_run.db"
    settings = {
        "week_forecast": {
            "validation_harness": {
                "enabled": True,
                "index_miss_streak_warn": 2,
                "auto_tighten_deploy_on_streak": False,
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
    yield {"reports": reports, "db_path": db_path, "settings": settings}
    reset_store()


def _verification(*, index_hit: bool = True) -> dict:
    return {
        "week_start": "2026-08-04",
        "week_end": "2026-08-08",
        "rows": [
            {
                "prediction": "大盘 +0.5%~+1.5%",
                "actual": "+1.0%",
                "verify": "✅ 命中区间" if index_hit else "❌ 偏离区间",
                "deviation": "+0.0%",
                "hit": index_hit,
            },
            {
                "prediction": "澜起 250-270元",
                "actual": "260元",
                "verify": "✅ 命中区间",
                "hit": True,
            },
        ],
        "hits": 2 if index_hit else 1,
        "total": 2,
        "accuracy_pct": 100.0 if index_hit else 50.0,
        "avg_deviation_pct": 0.5,
        "metrics": {
            "interval_hit_rate_pct": 100.0 if index_hit else 50.0,
            "interval_hits": 2 if index_hit else 1,
            "interval_total": 2,
            "direction_accuracy_pct": 100.0,
            "direction_hits": 1,
            "direction_total": 1,
        },
    }


def _forecast() -> dict:
    return {
        "week_start": "2026-08-04",
        "week_end": "2026-08-08",
        "structured_predictions": {
            "market": {
                "index_name": "沪深300",
                "change_pct_low": 0.5,
                "change_pct_high": 1.5,
                "change_pct_mid": 1.0,
                "macro_downside_extra_pct": 0.6,
            },
            "symbols": [],
        },
    }


def test_build_compact_validation_record_fields():
    with patch(
        "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
        return_value={"ok": True, "return_pct": 1.0},
    ), patch(
        "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
        return_value={"underperform_week_streak": 0, "threshold_pct": 0.0},
    ):
        record = build_compact_validation_record(_verification(), _forecast(), settings={})

    assert record["week_start"] == "2026-08-04"
    assert record["summary"]["interval_hit_rate_pct"] == 100.0
    assert record["index"]["band_hit"] is True
    assert record["index"]["macro_downside_extra_pct"] == 0.6
    assert record["index"]["actual_pct"] == 1.0


def test_persist_writes_files_and_index(validation_env):
    settings = validation_env["settings"]
    with patch(
        "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
        return_value={"ok": True, "return_pct": -1.2},
    ), patch(
        "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
        return_value={"underperform_week_streak": 1, "threshold_pct": 0.0},
    ):
        out = persist_forecast_validation_closure(
            _verification(index_hit=False),
            _forecast(),
            settings=settings,
        )

    assert out.get("skipped") is False
    week_file = Path(out["path"])
    assert week_file.exists()
    payload = json.loads(week_file.read_text(encoding="utf-8"))
    assert payload["index"]["band_hit"] is False
    assert "harness_signal" in payload
    assert payload["harness_signal"]["auto_tighten_enabled"] is False

    index = json.loads(validation_index_path().read_text(encoding="utf-8"))
    assert len(index["weeks"]) == 1
    assert index["weeks"][0]["index_band_hit"] is False


def test_persist_dual_writes_storage(validation_env):
    settings = validation_env["settings"]
    with patch(
        "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
        return_value={"ok": True, "return_pct": 0.5},
    ), patch(
        "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
        return_value={"underperform_week_streak": 0, "threshold_pct": 0.0},
    ):
        persist_forecast_validation_closure(_verification(), _forecast(), settings=settings)

    store = get_store(settings)
    rows = store.query_l2_scenarios(kind="forecast_validation", limit=5)
    assert len(rows) == 1
    assert rows[0]["scenario_key"] == "2026-08-04"


def test_index_miss_streak_signal(validation_env):
    prior = [
        {"week_start": "2026-07-28", "index_band_hit": False},
        {"week_start": "2026-08-04", "index_band_hit": False},
    ]
    assert index_band_miss_streak(prior, current_band_hit=False) == 3

    record = {
        "week_start": "2026-08-11",
        "index": {"band_hit": False, "macro_downside_extra_pct": 0.6},
        "benchmark_underperform": {"underperform_week_streak": 2},
    }
    validation_index_path().write_text(
        json.dumps({"weeks": prior}, ensure_ascii=False),
        encoding="utf-8",
    )
    streak = compute_index_band_miss_streak(record, settings=validation_env["settings"])
    assert streak >= 2

    signal = build_deploy_tighten_signal(record, settings=validation_env["settings"])
    assert signal["active"] is True
    assert signal["apply"] is False
    assert signal["index_miss_streak"] >= 2
    assert signal["benchmark_underperform_week_streak"] == 2