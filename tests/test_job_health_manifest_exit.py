# -*- coding: utf-8
"""AR-38: close auto-resume vs manifest exit / job_health consistency."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent_reach.daily_run import job_health as jh
from agent_reach.daily_run import run_manifest as rm
from agent_reach.daily_run import ops_trading_day_precheck as pre


def test_infer_schedule_exit_error_success_skipped():
    assert rm.infer_schedule_exit({"payload": {"job": "close", "error": "boom"}}) == 1
    assert rm.infer_schedule_exit({"payload": {"job": "close", "result": {}}}) == 0
    assert rm.infer_schedule_exit({"payload": {"skipped": True, "reason": "周末"}}) == 0
    assert rm.infer_schedule_exit(
        {"payload": {"skipped": True, "guard": "trade_date_backfill"}}
    ) == 1


def test_canonical_schedule_exit_uses_latest_manifest(tmp_path, monkeypatch):
    day = "2026-11-21"
    out = tmp_path / "runs" / day
    out.mkdir(parents=True)
    (out / "close_180001.json").write_text(
        json.dumps({"job": "close", "payload": {"error": "partial"}}) + "\n",
        encoding="utf-8",
    )
    (out / "close_180215.json").write_text(
        json.dumps({"job": "close", "payload": {"job": "close", "result": {}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rm, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(rm, "today_shanghai", lambda: date(2026, 11, 21))

    assert rm.canonical_schedule_exit("close") == 0


def test_job_health_aligned_with_manifest_exit(tmp_path, monkeypatch):
    settings = {"trade_calendar": {"enabled": False}}
    today = date(2026, 11, 21)
    prev = date(2026, 11, 20)
    jobs = {
        "close": {
            "consecutive_failures": 0,
            "last_success_at": datetime(2026, 11, 21, 10, 30, tzinfo=timezone.utc).isoformat(),
        }
    }
    day_dir = tmp_path / "runs" / today.isoformat()
    day_dir.mkdir(parents=True)
    (day_dir / "close_183000.json").write_text(
        json.dumps({"job": "close", "payload": {"job": "close"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rm, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(rm, "today_shanghai", lambda: today)
    with patch.object(jh, "today_shanghai", return_value=today), patch.object(
        jh, "trading_day_before", return_value=prev
    ):
        ok, _ = jh.job_health_aligned_with_manifest_exit(
            "close", settings=settings, jobs=jobs, day=today
        )
    assert ok

    (day_dir / "close_183100.json").write_text(
        json.dumps({"job": "close", "payload": {"error": "fail"}}) + "\n",
        encoding="utf-8",
    )
    with patch.object(jh, "today_shanghai", return_value=today), patch.object(
        jh, "trading_day_before", return_value=prev
    ):
        ok, detail = jh.job_health_aligned_with_manifest_exit(
            "close", settings=settings, jobs=jobs, day=today
        )
    assert not ok
    assert "exit=1" in detail


@patch("agent_reach.daily_run.job_health.record_job_outcome", return_value=1)
@patch("agent_reach.daily_run.job_health.notify_scheduled_job_failure")
@patch("agent_reach.daily_run.schedule.save_run_manifest")
@patch("agent_reach.daily_run.job_health.attempt_auto_resume_close")
@patch("agent_reach.daily_run.schedule._run_job_body")
def test_close_heal_resumed_skips_fail_manifest_and_raise(
    mock_body,
    mock_heal,
    mock_save,
    mock_notify,
    _record,
):
    from agent_reach.daily_run import schedule as sched

    mock_body.side_effect = RuntimeError("partial")
    healed = {"job": "close", "ok": True}
    mock_heal.return_value = {"resumed": True, "result": healed}

    settings = {"ops": {"auto_resume_close": True}}
    out = sched._run_scheduled_inner(
        "close",
        push=False,
        config=MagicMock(),
        settings=settings,
        t0=0.0,
        auto_heal=True,
    )
    assert out["ok"] is True
    assert out["schedule_meta"]["recovered_from_close_failure"] is True
    mock_notify.assert_not_called()
    mock_save.assert_not_called()
    mock_heal.assert_called_once()


def test_check_job_health_auto_resume_close_after_stale(tmp_path, monkeypatch):
    settings = {"trade_calendar": {"enabled": True}, "ops": {"auto_resume_close": True}}
    today = date(2026, 11, 21)
    prev = date(2026, 11, 20)
    fresh = datetime(2026, 11, 21, 10, 30, tzinfo=timezone.utc).isoformat()
    jobs_before = {
        "close": {
            "consecutive_failures": 1,
            "last_success_at": "2026-11-18T10:30:00+00:00",
            "last_error": "partial",
        },
        "morning": {"consecutive_failures": 0, "last_success_at": fresh},
    }
    path = tmp_path / "job_health.json"
    path.write_text(json.dumps({"jobs": jobs_before}), encoding="utf-8")
    monkeypatch.setattr(jh, "health_path", lambda: path)

    def fake_resume(**_kwargs):
        jh.record_job_outcome("close", success=True)
        return {"resumed": True, "result": {"job": "close"}}

    with patch.object(
        pre, "load_job_health", side_effect=lambda: json.loads(path.read_text(encoding="utf-8"))
    ), patch.object(jh, "today_shanghai", return_value=today), patch.object(
        jh, "trading_day_before", return_value=prev
    ), patch.object(
        jh, "close_has_resumable_checkpoint", return_value=True
    ), patch.object(
        jh, "attempt_auto_resume_close", side_effect=fake_resume
    ):
        results = pre.check_job_health(settings=settings)

    close = next(r for r in results if r.name == "job_health:close")
    assert close.ok
    assert "auto_resume_close" in close.detail