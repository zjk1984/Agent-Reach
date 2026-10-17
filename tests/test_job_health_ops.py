# -*- coding: utf-8
"""Ops job_health Feishu + auto-resume behavior."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from agent_reach.daily_run import job_health as jh


def test_feishu_ops_notify_skips_without_credentials():
    settings = {"ops": {"push_job_health_fail": True}}
    with patch("agent_reach.integrations.feishu.feishu_mode", return_value=None):
        assert jh.feishu_ops_notify_enabled(settings) is False
        out = jh.notify_scheduled_job_failure(
            "close",
            error="boom",
            streak=1,
            settings=settings,
        )
    assert out == {"skipped": True, "reason": "feishu_unconfigured_or_disabled"}


def test_feishu_ops_notify_respects_push_flag():
    settings = {"ops": {"push_job_health_fail": False}}
    with patch("agent_reach.integrations.feishu.feishu_mode", return_value="webhook"):
        assert jh.feishu_ops_notify_enabled(settings) is False


@patch("agent_reach.integrations.feishu.send_card", return_value={"code": 0})
@patch("agent_reach.integrations.feishu.feishu_mode", return_value="webhook")
def test_notify_scheduled_job_failure_sends(_mode, send_card):
    settings = {"ops": {"push_job_health_fail": True}}
    out = jh.notify_scheduled_job_failure(
        "morning",
        error="timeout",
        streak=2,
        settings=settings,
        config=MagicMock(),
    )
    assert out == {"code": 0}
    send_card.assert_called_once()
    args, kwargs = send_card.call_args
    assert "morning" in args[1]
    assert kwargs.get("template") == "red"


def test_assess_job_health_stale_close():
    settings = {"trade_calendar": {"enabled": False}}
    today = date(2026, 10, 20)
    prev = date(2026, 10, 19)
    jobs = {
        "close": {
            "consecutive_failures": 0,
            "last_success_at": "2026-10-16T10:30:00+00:00",
        },
    }
    with patch.object(jh, "today_shanghai", return_value=today), patch.object(
        jh, "trading_day_before", return_value=prev
    ):
        ok, detail = jh.assess_job_health_entry("close", settings=settings, jobs=jobs)
    assert not ok
    assert "2026-10-16" in detail


def test_close_has_resumable_checkpoint(tmp_path, monkeypatch):
    from agent_reach.daily_run import job_checkpoint as jc

    ck_dir = tmp_path / "checkpoints"
    ck_dir.mkdir()
    day = "2026-10-20"
    path = ck_dir / f"close_{day}.json"
    path.write_text(
        '{"job":"close","date":"2026-10-20","steps":{"688008":{"status":"done"},"002273":{"status":"pending"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(jc, "step_checkpoint_dir", lambda: ck_dir)
    monkeypatch.setattr(jc, "today_shanghai", lambda: date(2026, 10, 20))
    assert jh.close_has_resumable_checkpoint() is True


def test_attempt_auto_resume_close_skips_when_disabled():
    settings = {"ops": {"auto_resume_close": False}}
    with patch.object(jh, "close_has_resumable_checkpoint", return_value=True):
        out = jh.attempt_auto_resume_close(settings=settings)
    assert out["skipped"] and out["reason"] == "auto_resume_close_disabled"


@patch("agent_reach.daily_run.schedule.run_scheduled", return_value={"job": "close", "ok": True})
def test_attempt_auto_resume_close_runs_schedule(run_scheduled):
    settings = {"ops": {"auto_resume_close": True}}
    with patch.object(jh, "close_has_resumable_checkpoint", return_value=True):
        out = jh.attempt_auto_resume_close(settings=settings, push=False)
    assert out["resumed"] is True
    run_scheduled.assert_called_once_with(
        "close",
        push=False,
        config=None,
        auto_heal=False,
    )


@patch("agent_reach.daily_run.job_health.notify_ops_precheck_fail")
def test_precheck_main_notifies_on_fail(notify_mock, capsys):
    from agent_reach.daily_run import ops_trading_day_precheck as pre

    fail = pre.CheckResult("disk", False, "low space")
    with patch.object(
        pre,
        "run_precheck",
        return_value=([fail], 1),
    ), patch.object(pre, "load_settings", return_value={"ops": {}}):
        code = pre.main(["--force-non-trading", "--no-fetch"])
    assert code == 1
    notify_mock.assert_called_once()


@patch("agent_reach.daily_run.job_health.notify_ops_precheck_fail")
def test_precheck_main_skips_notify_on_pass(notify_mock):
    from agent_reach.daily_run import ops_trading_day_precheck as pre

    ok = pre.CheckResult("git", True, "fine")
    with patch.object(pre, "run_precheck", return_value=([ok], 0)):
        code = pre.main(["--force-non-trading", "--no-fetch"])
    assert code == 0
    notify_mock.assert_not_called()
