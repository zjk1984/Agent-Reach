# -*- coding: utf-8
"""Tests for expert enable/disable toggles."""

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.team import experts_enabled, team_first_enabled


class TestExpertsToggle:
    def test_disabled_by_default_in_config(self):
        cfg = load_settings()
        assert cfg.get("team", {}).get("enabled") is False
        assert experts_enabled(cfg, workflow="morning") is False
        assert experts_enabled(cfg, workflow="close") is False
        assert experts_enabled(cfg, workflow="intraday") is False

    def test_enabled_when_team_on(self):
        cfg = load_settings()
        cfg = {
            **cfg,
            "team": {
                **(cfg.get("team") or {}),
                "enabled": True,
                "morning_team_first": True,
                "close_team_first": True,
                "intraday_experts": True,
            },
        }
        assert experts_enabled(cfg, workflow="morning") is True
        assert team_first_enabled(cfg, workflow="morning") is True
