# -*- coding: utf-8
"""Tests for 60s hot-news Docker deploy."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent_reach.daily_run.hot_news_deploy import (
    CONTAINER_NAME,
    LOCAL_BASE_URL,
    install_60s_local,
    merge_user_hot_news_settings,
    status_60s,
    stop_container,
)


class TestMergeSettings:
    def test_merge_writes_hot_news_deploy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.hot_news_deploy.Path.home",
            lambda: tmp_path,
        )
        out = merge_user_hot_news_settings()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["hot_news"]["base_urls"][0] == LOCAL_BASE_URL
        assert data["hot_news"]["deploy"]["container_name"] == CONTAINER_NAME


class TestInstall60s:
    def test_install_starts_container(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.hot_news_deploy.Path.home",
            lambda: tmp_path,
        )
        with (
            patch("agent_reach.daily_run.hot_news_deploy.container_running", return_value=False),
            patch("agent_reach.daily_run.hot_news_deploy.docker_path", return_value="/usr/bin/docker"),
            patch(
                "agent_reach.daily_run.hot_news_deploy.resolve_local_base_url",
                side_effect=[None, LOCAL_BASE_URL],
            ),
            patch("agent_reach.daily_run.hot_news_deploy.start_container", return_value=(True, "started")),
            patch("agent_reach.daily_run.hot_news_deploy.wait_healthy", return_value=(True, LOCAL_BASE_URL)),
        ):
            result = install_60s_local(pull=False)
        assert result["ok"] is True
        assert result["active_base_url"] == LOCAL_BASE_URL

    def test_install_without_docker_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.hot_news_deploy.Path.home",
            lambda: tmp_path,
        )
        with (
            patch("agent_reach.daily_run.hot_news_deploy.docker_path", return_value=None),
            patch(
                "agent_reach.daily_run.hot_news_deploy.resolve_local_base_url",
                return_value="https://60s.viki.moe",
            ),
        ):
            result = install_60s_local()
        assert result["ok"] is True
        assert result["active_base_url"] == "https://60s.viki.moe"

    def test_install_skips_when_already_healthy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.hot_news_deploy.Path.home",
            lambda: tmp_path,
        )
        with (
            patch("agent_reach.daily_run.hot_news_deploy.container_running", return_value=True),
            patch("agent_reach.daily_run.hot_news_deploy.docker_path", return_value="/usr/bin/docker"),
            patch(
                "agent_reach.daily_run.hot_news_deploy.resolve_local_base_url",
                return_value=LOCAL_BASE_URL,
            ),
        ):
            result = install_60s_local()
        assert result["ok"] is True
        assert "already healthy" in result["message"]


class TestStatusAndStop:
    def test_status_local_ok(self):
        with (
            patch("agent_reach.daily_run.hot_news_deploy.docker_path", return_value="/usr/bin/docker"),
            patch("agent_reach.daily_run.hot_news_deploy.container_running", return_value=True),
            patch(
                "agent_reach.daily_run.hot_news_deploy.resolve_local_base_url",
                return_value=LOCAL_BASE_URL,
            ),
        ):
            st = status_60s()
        assert st["local_reachable"] is True
        assert st["container_running"] is True

    def test_stop_container(self):
        with (
            patch("agent_reach.daily_run.hot_news_deploy.docker_path", return_value="/usr/bin/docker"),
            patch("agent_reach.daily_run.hot_news_deploy.container_exists", return_value=True),
            patch("agent_reach.daily_run.hot_news_deploy.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            ok, msg = stop_container(remove=True)
        assert ok is True
        assert CONTAINER_NAME in msg
