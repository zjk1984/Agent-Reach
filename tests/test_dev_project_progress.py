# -*- coding: utf-8
"""Tests for dev / coordinator project progress (Feishu markdown file)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.daily_run.dev_project_progress import (
    compact_dev_progress_for_feishu,
    dev_project_progress_feishu_card,
    dev_project_progress_feishu_enabled,
    extract_blocker_hints,
    feishu_template_for_dev_markdown,
    load_dev_project_progress_markdown,
    resolve_dev_project_progress_path,
)


def test_dev_project_progress_feishu_enabled_flag():
    assert not dev_project_progress_feishu_enabled({})
    assert dev_project_progress_feishu_enabled(
        {"ops": {"dev_project_progress_feishu": {"enabled": True}}}
    )


def test_resolve_and_load_markdown(tmp_path: Path):
    p = tmp_path / "dev-project-progress.md"
    p.write_text("# Dev\n\n## 阻塞\n- 无\n", encoding="utf-8")
    assert resolve_dev_project_progress_path(str(p)) == p.resolve()
    assert load_dev_project_progress_markdown(p) == "# Dev\n\n## 阻塞\n- 无"


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_dev_project_progress_markdown(tmp_path / "missing.md")


def test_blocker_extraction_and_template():
    md = "# 进展\n\n## 阻塞\n- CI 红灯\n"
    assert extract_blocker_hints(md) == ["CI 红灯"]
    assert feishu_template_for_dev_markdown(md) == "red"

    ok_md = "## 阻塞\n- 无\n"
    assert extract_blocker_hints(ok_md) == []
    assert feishu_template_for_dev_markdown(ok_md) == "blue"


def test_dev_project_progress_feishu_card_title():
    md = "## 已完成\n- #150 merged\n\n## 阻塞\n- 无\n"
    title, body, tpl = dev_project_progress_feishu_card(md, as_of="2026-11-17")
    assert "Agent-Reach 开发进展" in title
    assert "2026-11-17" in title
    assert "#150" in body
    assert tpl == "green"


def test_compact_truncates_long_body():
    long = "x" * 4000
    out = compact_dev_progress_for_feishu(long, max_chars=100)
    assert len(out) < 200
    assert "截断" in out


@patch("agent_reach.integrations.feishu.send_card", return_value={"code": 0})
@patch("agent_reach.integrations.feishu.feishu_mode", return_value="webhook")
def test_ops_cli_dev_project_progress_push(_mode, send_card, tmp_path: Path):
    from agent_reach.daily_run import ops_cli

    report = tmp_path / "dev.md"
    report.write_text("## 队列\n- #151\n", encoding="utf-8")
    args = Namespace(ops_action="dev-project-progress", file=str(report), dry_run=False, push=True)
    settings = {"ops": {"dev_project_progress_feishu": {"enabled": True}}}
    with patch.object(ops_cli, "load_settings", return_value=settings):
        ops_cli.cmd_ops(args)
    send_card.assert_called_once()
    call_kw = send_card.call_args
    assert "Agent-Reach 开发进展" in call_kw[0][1]


def test_ops_cli_dev_project_progress_dry_run_no_send(tmp_path: Path):
    from agent_reach.daily_run import ops_cli

    report = tmp_path / "dev.md"
    report.write_text("card-body-only", encoding="utf-8")
    args = Namespace(ops_action="dev-project-progress", file=str(report), dry_run=True, push=False)
    with patch.object(ops_cli, "load_settings", return_value={}), patch(
        "agent_reach.integrations.feishu.send_card"
    ) as send_card:
        ops_cli.cmd_ops(args)
    send_card.assert_not_called()


def test_ops_cli_dev_project_progress_skips_when_disabled(tmp_path: Path, capsys):
    from agent_reach.daily_run import ops_cli

    report = tmp_path / "dev.md"
    report.write_text("body", encoding="utf-8")
    args = Namespace(ops_action="dev-project-progress", file=str(report), dry_run=False, push=True)
    with patch.object(ops_cli, "load_settings", return_value={}), patch(
        "agent_reach.integrations.feishu.send_card"
    ) as send_card:
        ops_cli.cmd_ops(args)
    send_card.assert_not_called()
    err = capsys.readouterr().err
    assert "dev_project_progress_feishu.enabled is false" in err