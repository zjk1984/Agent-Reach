# -*- coding: utf-8
"""Tests for optimizer harness + close job dedupe."""

import json
from pathlib import Path

import agent_reach.daily_run.harness as harness_mod
from agent_reach.daily_run.harness import refine_after_job
from agent_reach.daily_run.optimizer import grid_search_optimize, save_optimized_settings
from agent_reach.daily_run.optimizer_harness import optimize_to_harness_evidence
from agent_reach.daily_run.harness_git import resolve_harness_state_path
from agent_reach.daily_run.settings import load_settings


def _optimizer_harness_test_settings(**overrides) -> dict:
    """Repo-neutral harness settings: CI has no user override and forge may block refine."""
    settings = load_settings()
    settings.setdefault("harness", {})
    settings["harness"]["enabled"] = True
    settings["harness"]["threshold_evolution_mode"] = "harness"
    settings["harness"]["jobs"] = {"optimize": True}
    settings["harness"].setdefault("forge_gates", {})["enabled"] = False
    settings.setdefault("optimizer", {})["harness_evolve"] = True
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            block = dict(settings[key])
            block.update(value)
            settings[key] = block
        else:
            settings[key] = value
    return settings


def test_optimize_to_harness_evidence_has_policy():
    history = json.loads(
        Path("config/daily_run_history.example.json").read_text(encoding="utf-8")
    )
    result = grid_search_optimize(history, load_settings(), objective="excess_return")
    ev = optimize_to_harness_evidence(result)
    assert ev["policy"]
    assert any("macro_veto=" in p for p in ev["policy"])
    assert ev["playbook"]


def test_save_optimized_settings_harness_mode_skips_thresholds(tmp_path):
    history = json.loads(
        Path("config/daily_run_history.example.json").read_text(encoding="utf-8")
    )
    settings = _optimizer_harness_test_settings(thresholds={"macro_veto": 99})

    result = grid_search_optimize(history, settings)
    out = save_optimized_settings(result, settings, path=tmp_path / "opt.json")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["thresholds"].get("macro_veto") == 99
    assert saved["optimizer"]["last_run"]["harness_mode"] is True
    state_path = resolve_harness_state_path(settings)
    assert state_path.is_file(), f"missing harness state at {state_path}"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    policy_blob = json.dumps(state.get("entries", {}).get("policy", {}), ensure_ascii=False)
    assert "macro_veto=" in policy_blob


def test_save_optimized_settings_harness_mode_strips_stale_backtest_keys(tmp_path):
    """Regression: a prior fixed-mode run may have left static backtest.macro_veto /
    aggressive_entry in the persisted file. Harness mode must self-heal (remove) them
    instead of silently re-persisting the pollution on every optimizer run."""
    history = json.loads(
        Path("config/daily_run_history.example.json").read_text(encoding="utf-8")
    )
    settings = _optimizer_harness_test_settings(
        backtest={
            "default_initial_capital": 100000,
            "commission_rate": 0.0015,
            "macro_veto": 40,
            "aggressive_entry": 50,
        }
    )

    result = grid_search_optimize(history, settings)
    out = save_optimized_settings(result, settings, path=tmp_path / "opt.json")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert "macro_veto" not in saved["backtest"]
    assert "aggressive_entry" not in saved["backtest"]
    assert saved["backtest"]["default_initial_capital"] == 100000


def test_close_layer_a_skips_verify_when_specialized_jobs_on(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_mod, "_state_path", lambda: tmp_path / "harness_state.json")
    settings = {
        "harness": {
            "enabled": True,
            "jobs": {"close": True, "verify": True, "close_improve": True},
        }
    }
    close_evidence = {
        "verify": {
            "summary": "验证完成",
            "recommendations": ["明日激进建仓"],
            "code": "688008",
        },
        "name": "澜起科技",
        "portfolio_summary": {"daily_pnl": 1200.0, "daily_pnl_pct": 0.5},
    }
    ref = refine_after_job("close", evidence=close_evidence, settings=settings)
    assert ref.get("skipped") is False
    state = json.loads((tmp_path / "harness_state.json").read_text(encoding="utf-8"))
    blob = json.dumps(state, ensure_ascii=False)
    assert "激进建仓" not in blob
    assert "收盘组合盈亏" in blob
