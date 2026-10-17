# -*- coding: utf-8
"""Unit tests for ops trading-day precheck helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from agent_reach.daily_run import ops_trading_day_precheck as pre


def test_check_job_health_accepts_prev_trading_day():
    settings = {"trade_calendar": {"enabled": False}}
    today = date(2026, 10, 20)  # Tuesday
    prev = date(2026, 10, 19)

    jobs = {
        "close": {
            "consecutive_failures": 0,
            "last_success_at": "2026-10-19T10:30:00+00:00",
        },
        "morning": {
            "consecutive_failures": 0,
            "last_success_at": "2026-10-19T00:30:00+00:00",
        },
    }

    with patch.object(
        pre, "load_job_health", return_value={"jobs": jobs}
    ), patch(
        "agent_reach.daily_run.job_health.today_shanghai",
        return_value=today,
    ), patch(
        "agent_reach.daily_run.job_health.trading_day_before",
        return_value=prev,
    ):
        results = pre.check_job_health(settings=settings)

    assert len(results) == 2
    assert all(r.ok for r in results)


def test_check_job_health_fails_stale_close():
    settings = {"trade_calendar": {"enabled": False}}
    today = date(2026, 10, 20)
    prev = date(2026, 10, 19)

    jobs = {
        "close": {
            "consecutive_failures": 0,
            "last_success_at": "2026-10-16T10:30:00+00:00",
        },
        "morning": {
            "consecutive_failures": 0,
            "last_success_at": "2026-10-19T00:30:00+00:00",
        },
    }

    with patch.object(
        pre, "load_job_health", return_value={"jobs": jobs}
    ), patch(
        "agent_reach.daily_run.job_health.today_shanghai",
        return_value=today,
    ), patch(
        "agent_reach.daily_run.job_health.trading_day_before",
        return_value=prev,
    ):
        results = pre.check_job_health(settings=settings)

    close = next(r for r in results if r.name == "job_health:close")
    assert not close.ok


def test_run_precheck_skips_checks_on_non_trading_day():
    repo = MagicMock()
    with patch.object(pre, "is_trading_day", return_value=(False, "周末")), patch.object(
        pre, "check_git_main_sync"
    ) as git_mock:
        results, code = pre.run_precheck(repo, skip_non_trading=True)
    git_mock.assert_not_called()
    assert code == 0
    assert len(results) == 1


def test_check_doctor_smoke_flags_critical_error():
    channels = {
        "xueqiu": {"status": "error", "name": "雪球", "message": "down"},
        "twitter": {"status": "error", "name": "Twitter", "message": "n/a"},
    }
    integrations = {"feishu": {"status": "ok"}}

    with patch(
        "agent_reach.doctor.check_all", return_value=channels
    ), patch("agent_reach.doctor.check_integrations", return_value=integrations), patch(
        "agent_reach.config.Config"
    ):
        result = pre.check_doctor_smoke()

    assert not result.ok
