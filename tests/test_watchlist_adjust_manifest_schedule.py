# -*- coding: utf-8
"""AR-41: watchlist_adjust on success and failure schedule manifests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agent_reach.daily_run.watchlist_adjust_manifest import (
    attach_watchlist_adjust_to_manifest_payload,
    clear_watchlist_adjust_manifest_pending,
    record_watchlist_adjust_for_manifest,
)
from agent_reach.daily_run.watchlist_manager import (
    watchlist_adjust_manifest_summary,
    watchlist_adjust_result_from_dict,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    clear_watchlist_adjust_manifest_pending()
    yield
    clear_watchlist_adjust_manifest_pending()


def test_watchlist_adjust_manifest_summary_error_status():
    summary = watchlist_adjust_manifest_summary(None, enabled=True, error="quote timeout")
    assert summary["status"] == "error"
    assert "quote timeout" in summary["message"]


def test_attach_watchlist_adjust_from_pending_stash():
    wl_dict = {"applied": False, "message": "观察池无变更", "changes": []}
    record_watchlist_adjust_for_manifest(
        watchlist_adjust=wl_dict,
        watchlist_adjust_summary=watchlist_adjust_manifest_summary(
            watchlist_adjust_result_from_dict(wl_dict),
            enabled=True,
        ),
    )
    payload = {"job": "morning", "error": "002583: audit failed"}
    attach_watchlist_adjust_to_manifest_payload(payload)
    assert payload["watchlist_adjust"]["message"] == "观察池无变更"
    assert payload["watchlist_adjust_summary"]["status"] == "unchanged"


@patch("agent_reach.daily_run.schedule.save_run_manifest")
@patch("agent_reach.daily_run.schedule._run_job_body")
@patch("agent_reach.daily_run.job_health.record_job_outcome")
def test_morning_failure_manifest_includes_watchlist_adjust(
    mock_record,
    mock_job_body,
    mock_save_manifest,
):
    from agent_reach.daily_run.schedule import _run_scheduled_inner

    mock_record.return_value = 1
    mock_save_manifest.return_value = None
    record_watchlist_adjust_for_manifest(
        watchlist_adjust={"applied": False, "message": "缺报价", "changes": []},
        watchlist_adjust_summary={
            "status": "unchanged",
            "applied": False,
            "change_count": 0,
            "message": "缺报价",
            "changes": [],
        },
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("002583: audit")

    mock_job_body.side_effect = _raise

    with patch(
        "agent_reach.daily_run.job_health.notify_scheduled_job_failure",
    ), patch(
        "agent_reach.daily_run.schedule._apply_scheduled_guard_harness",
    ), patch(
        "agent_reach.daily_run.schedule._attach_manifest_harness_summary",
    ):
        with pytest.raises(RuntimeError):
            _run_scheduled_inner(
                "morning",
                push=False,
                config=None,
                settings={},
                t0=0.0,
                auto_heal=True,
            )

    fail_payload = mock_save_manifest.call_args[0][1]
    assert fail_payload.get("watchlist_adjust", {}).get("message") == "缺报价"
    assert fail_payload.get("watchlist_adjust_summary", {}).get("status") == "unchanged"


@patch("agent_reach.daily_run.berkshire.pipeline.maybe_adjust_watchlist_morning")
@patch("agent_reach.daily_run.intraday.record_morning_scan", return_value={"scan": {"scan_id": "S1"}})
@patch("agent_reach.daily_run.workflows.run_morning")
@patch("agent_reach.daily_run.symbol_runner.build_and_save")
@patch("agent_reach.daily_run.symbol_runner.load_portfolio")
def test_run_morning_for_symbols_returns_adjust_summary(
    mock_pf,
    mock_build,
    mock_run,
    mock_morning_scan,
    mock_wl_adjust,
    tmp_path,
):
    from agent_reach.daily_run.symbol_runner import run_morning_for_symbols
    from agent_reach.daily_run.settings import load_settings
    from tests.test_daily_run_per_symbol import PORTFOLIO

    mock_pf.return_value = PORTFOLIO
    mock_build.side_effect = [
        ({"code": "688008", "name": "澜起科技"}, tmp_path / "preview.json"),
        ({"code": "688008", "name": "澜起科技"}, tmp_path / "a.json"),
    ]
    mock_wl_adjust.return_value = (
        PORTFOLIO,
        {"applied": False, "message": "观察池无变更", "changes": []},
    )
    mock_run.return_value = {
        "snapshot": {"code": "688008"},
        "evaluation": {"report": {}},
        "feishu": {"ok": 1},
    }
    cfg = load_settings()
    cfg = {**cfg, "schedule": {**(cfg.get("schedule") or {}), "symbols_mode": "holdings"}}

    result = run_morning_for_symbols(settings=cfg, push=False, symbols=["688008"])
    assert result["watchlist_adjust_summary"]["status"] == "unchanged"
    assert result["watchlist_adjust"]["message"] == "观察池无变更"


@patch("agent_reach.daily_run.run_manifest.runs_dir")
def test_success_manifest_written_via_schedule(mock_runs, tmp_path):
    from agent_reach.daily_run.run_manifest import save_run_manifest

    runs = tmp_path / "runs"
    mock_runs.return_value = runs
    payload = {
        "job": "morning",
        "watchlist_adjust": {"applied": True, "message": "ok", "changes": []},
        "watchlist_adjust_summary": watchlist_adjust_manifest_summary(None, enabled=True),
    }
    path = save_run_manifest("morning", payload, duration_ms=1.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "watchlist_adjust" in data["payload"]
    assert "watchlist_adjust_summary" in data["payload"]