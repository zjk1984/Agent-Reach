# -*- coding: utf-8
"""Unit tests for ops trading-day precheck helpers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
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


def test_deep_merge_missing_keys_preserves_user():
    user = {"watchlist": {"hot_topic_adjust_enabled": True, "extra": 1}}
    prof = {
        "_profile": "x",
        "watchlist": {"hot_topic_adjust_enabled": False, "weekly_candidates_enabled": True},
        "ops": {"precheck_auto_sync": {"enabled": True}},
    }
    merged = json.loads(json.dumps(user))
    added = pre.deep_merge_missing_keys(merged, prof)
    assert "watchlist.hot_topic_adjust_enabled" not in added
    assert user["watchlist"]["hot_topic_adjust_enabled"] is True
    assert merged["watchlist"]["weekly_candidates_enabled"] is True
    assert merged["ops"]["precheck_auto_sync"]["enabled"] is True


def test_maybe_auto_sync_disabled_returns_empty():
    repo = Path("/tmp/repo")
    settings = {"ops": {"precheck_auto_sync": {"enabled": False}}}
    assert pre.maybe_auto_sync_repo(repo, settings) == []


def test_maybe_auto_sync_refuses_dirty_tree():
    repo = Path("/tmp/repo")
    settings = {"ops": {"precheck_auto_sync": {"enabled": True, "git_pull": True}}}

    def fake_git(_root, *args):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return MagicMock(stdout="main\n", returncode=0)
        if args[0] == "status":
            return MagicMock(stdout=" M foo.py\n", returncode=0)
        return MagicMock(stdout="", returncode=0)

    with patch.object(pre, "_run_git", side_effect=fake_git):
        results = pre.maybe_auto_sync_repo(repo, settings, fetch=False)

    assert any(r.name == "auto_sync" and "未提交" in r.detail for r in results)
    assert not any(r.name == "auto_sync:git" and "pull" in r.detail.lower() for r in results)


def test_maybe_auto_sync_pull_and_pip_when_behind(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "constraints.txt").write_text("# test\n")
    settings = {"ops": {"precheck_auto_sync": {"enabled": True, "git_pull": True, "pip_editable": True}}}

    calls: list[list[str]] = []

    def fake_git(_root, *args):
        calls.append(args)
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return MagicMock(stdout="main\n", returncode=0)
        if args == ("status", "--porcelain"):
            return MagicMock(stdout="", returncode=0)
        if args == ("fetch", "origin", "main"):
            return MagicMock(stdout="", returncode=0)
        if args == ("rev-parse", "HEAD"):
            if len([c for c in calls if c == ("rev-parse", "HEAD")]) <= 1:
                return MagicMock(stdout="aaa\n", returncode=0)
            return MagicMock(stdout="bbb\n", returncode=0)
        if args == ("rev-parse", "origin/main"):
            return MagicMock(stdout="bbb\n", returncode=0)
        if args == ("rev-list", "--count", "HEAD..origin/main"):
            return MagicMock(stdout="2\n", returncode=0)
        if args == ("rev-list", "--count", "origin/main..HEAD"):
            return MagicMock(stdout="0\n", returncode=0)
        if args == ("pull", "--ff-only", "origin", "main"):
            return MagicMock(stdout="", returncode=0)
        if args == ("rev-parse", "--short", "HEAD"):
            return MagicMock(stdout="bbb1234\n", returncode=0)
        return MagicMock(stdout="", returncode=0)

    pip_mock = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch.object(pre, "_run_git", side_effect=fake_git), patch(
        "agent_reach.daily_run.ops_trading_day_precheck.subprocess.run", return_value=pip_mock
    ) as run_mock:
        results = pre.maybe_auto_sync_repo(repo, settings, fetch=True)

    assert any(r.name == "auto_sync:git" and "pull" in r.detail for r in results)
    assert any(r.name == "auto_sync:pip" and r.ok for r in results)
    assert ("pull", "--ff-only", "origin", "main") in calls
    pip_cmds = [c[0] for c in run_mock.call_args_list if c[0][0]]
    assert any("pip" in str(cmd) for cmd in pip_cmds)


def test_run_precheck_invokes_auto_sync_before_git(tmp_path):
    repo = tmp_path
    settings = {
        "trade_calendar": {"enabled": False},
        "ops": {"precheck_auto_sync": {"enabled": True}},
    }
    sync_result = [pre.CheckResult("auto_sync:git", True, "ok", severity="info")]

    with patch.object(pre, "is_trading_day", return_value=(True, "ok")), patch.object(
        pre, "maybe_auto_sync_repo", return_value=sync_result
    ) as sync_mock, patch.object(
        pre, "check_git_main_sync", return_value=pre.CheckResult("git", True, "synced")
    ) as git_mock, patch.object(
        pre, "check_pip_editable", return_value=pre.CheckResult("pip", True, "ok")
    ), patch.object(pre, "check_job_health", return_value=[]), patch.object(
        pre, "check_doctor_smoke", return_value=pre.CheckResult("doctor", True, "ok")
    ), patch.object(
        pre, "check_disk_space", return_value=pre.CheckResult("disk", True, "ok")
    ), patch.object(
        pre, "check_worker_note", return_value=pre.CheckResult("worker", True, "ok")
    ):
        results, code = pre.run_precheck(repo, settings=settings, skip_non_trading=False)

    sync_mock.assert_called_once()
    git_mock.assert_called_once()
    assert results[1].name == "auto_sync:git"
    assert code == 0