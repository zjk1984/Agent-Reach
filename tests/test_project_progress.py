# -*- coding: utf-8
"""Tests for daily project progress report."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from agent_reach.daily_run.project_progress import (
    build_project_progress_payload,
    collect_blockers,
    project_progress_feishu_card,
    project_progress_feishu_enabled,
    render_project_progress_markdown,
    resolve_git_head,
)


def test_project_progress_feishu_enabled_flag():
    assert not project_progress_feishu_enabled({})
    assert project_progress_feishu_enabled({"ops": {"project_progress_feishu": {"enabled": True}}})


def test_render_markdown_sections(tmp_path, monkeypatch):
    jh = tmp_path / "job_health.json"
    jh.write_text(
        json.dumps(
            {
                "jobs": {
                    "morning": {
                        "last_success_at": "2026-11-17T01:00:00+00:00",
                        "consecutive_failures": 0,
                    },
                    "close": {
                        "last_success_at": "2026-11-17T10:30:00+00:00",
                        "consecutive_failures": 0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.project_progress.load_job_health",
        lambda: json.loads(jh.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.project_progress.reconcile_stale_job_health",
        lambda **_: False,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.project_progress.today_shanghai",
        lambda: date(2026, 11, 17),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.project_progress.is_trading_day",
        lambda *a, **k: (True, ""),
    )

    with patch(
        "agent_reach.daily_run.snapshot_builder.load_portfolio",
        return_value={"cash": 50000, "total": 100000, "cash_ratio": 0.5},
    ), patch(
        "agent_reach.daily_run.daily_pnl_history.load_daily_pnl_history",
        return_value=[],
    ), patch(
        "agent_reach.daily_run.project_progress.resolve_git_head",
        return_value={"head_short": "abc1234", "branch": "main", "repo_root": "/tmp/repo"},
    ), patch(
        "agent_reach.integrations.feishu.feishu_mode",
        return_value="webhook",
    ):
        payload = build_project_progress_payload(settings={"trade_calendar": {"enabled": False}})

    md = render_project_progress_markdown(payload)
    assert "## 运维实况" in md
    assert "## 代码版本" in md
    assert "`abc1234`" in md
    assert "## job_health" in md
    assert "## 阻塞提示" in md


@patch("agent_reach.integrations.feishu.send_card", return_value={"code": 0})
@patch("agent_reach.integrations.feishu.feishu_mode", return_value="webhook")
def test_ops_cli_project_progress_push(_mode, send_card):
    from agent_reach.daily_run import ops_cli

    fake = MagicMock()
    fake.to_dict.return_value = {"as_of": "2026-11-17", "blockers": ["无"]}
    args = argparse_namespace(
        ops_action="project-progress",
        json=False,
        output="",
        dry_run=False,
        push=True,
    )
    settings = {"ops": {"project_progress_feishu": {"enabled": True}}}
    with patch.object(ops_cli, "load_settings", return_value=settings), patch.object(
        ops_cli,
        "load_and_build_project_progress",
        return_value=fake,
    ), patch.object(
        ops_cli,
        "render_project_progress_markdown",
        return_value="# ok",
    ), patch.object(
        ops_cli,
        "project_progress_feishu_card",
        return_value=("title", "body", "green"),
    ):
        ops_cli.cmd_ops(args)

    send_card.assert_called_once()


def test_ops_cli_project_progress_dry_run_no_send():
    from agent_reach.daily_run import ops_cli

    fake = MagicMock()
    args = argparse_namespace(
        ops_action="project-progress",
        json=False,
        output="",
        dry_run=True,
        push=True,
    )
    with patch.object(ops_cli, "load_settings", return_value={}), patch.object(
        ops_cli,
        "load_and_build_project_progress",
        return_value=fake,
    ), patch.object(
        ops_cli,
        "render_project_progress_markdown",
        return_value="# md",
    ), patch.object(
        ops_cli,
        "project_progress_feishu_card",
        return_value=("t", "card-body", "blue"),
    ), patch(
        "agent_reach.integrations.feishu.send_card"
    ) as send_card:
        ops_cli.cmd_ops(args)
    send_card.assert_not_called()


def test_collect_blockers_flags_feishu_missing():
    hints = collect_blockers(
        settings={},
        job_health={"jobs": {}},
        feishu_configured=False,
        push_enabled=True,
    )
    assert any("飞书未配置" in h for h in hints)


def test_resolve_git_head_in_repo():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    meta = resolve_git_head(root)
    assert meta.get("head_short") or meta.get("error")


def test_project_progress_feishu_card_template():
    payload = {
        "as_of": "2026-11-17",
        "trading_day": True,
        "portfolio": {"nav": 100000, "cash": 50000},
        "git": {"head_short": "deadbeef", "branch": "main"},
        "job_rows": [{"job": "close", "last_success_at": None, "consecutive_failures": 2}],
        "job_assessments": [{"job": "close", "ok": False, "detail": "stale"}],
        "blockers": ["close stale"],
    }
    title, body, tpl = project_progress_feishu_card(payload)
    assert "2026-11-17" in title
    assert "deadbeef" in body
    assert tpl == "red"


def argparse_namespace(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)