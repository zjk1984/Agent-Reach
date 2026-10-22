# -*- coding: utf-8
"""Prod profile overlays: fund_moderate_cash deep-merge smoke."""

from __future__ import annotations

import json
from pathlib import Path

from agent_reach.daily_run.deploy_signal_policy import deploy_signal_cfg, signal_strength_deploy_ratio
from agent_reach.daily_run.harness_policy import min_cash_ratio_default, resolve_harness_threshold_overrides
from agent_reach.daily_run.harness import HarnessState
from agent_reach.daily_run.harness_reading_signals import reading_signals_cfg
from agent_reach.daily_run.settings import load_settings


def _deep_merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = v
    return a


def _merged_moderate_settings() -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    base = load_settings(repo_root / "config" / "daily_run_settings.json")
    prof = json.loads((repo_root / "config/profiles/fund_moderate_cash.json").read_text())
    return _deep_merge(base, prof)


class TestFundModerateCashProfile:
    def test_profile_json_loads_and_merge_keys(self):
        settings = _merged_moderate_settings()
        assert settings["harness"]["min_cash_ratio_mode"] == "fixed"
        assert settings["thresholds"]["min_cash_ratio"] == 0.28
        cap = settings["intraday"]["technical_watch"]["min_cash_ratio_cap"]
        assert cap["register_min_cash_ratio"] == 0.3
        assert cap["attack_min_cash_ratio"] == 0.2
        assert settings["watchlist"]["hot_topic_adjust_enabled"] is False

    def test_fixed_min_cash_ignores_high_cash_memory_overlay(self):
        settings = _merged_moderate_settings()
        state = HarnessState()
        effective = resolve_harness_threshold_overrides(
            state,
            settings.get("thresholds") or {},
            settings=settings,
        )
        assert effective["min_cash_ratio"] == 0.28
        assert min_cash_ratio_default(settings) == 0.28

    def test_deploy_and_reading_signal_overrides(self):
        settings = _merged_moderate_settings()
        cfg = deploy_signal_cfg(settings)
        assert cfg["weak_deploy_ratio"] == 0.35
        assert cfg["medium_deploy_ratio"] == 0.55
        ratio, _ = signal_strength_deploy_ratio(mss_delta=3.5, settings=settings)
        assert ratio == 0.55
        reading = reading_signals_cfg(settings)
        assert reading["recovery_min_mss"] == 50.0
        assert reading["recovery_min_delta"] == 3.0
