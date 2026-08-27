# -*- coding: utf-8
"""Tests for harness-evolved config policy modules (#1–#6)."""

from unittest.mock import patch

from agent_reach.daily_run.data_audit_policy import (
    data_audit_cfg,
    parse_data_audit_policy_line,
    resolve_harness_data_audit_policy,
)
from agent_reach.daily_run.expert_consensus_policy import (
    expert_consensus_cfg,
    parse_expert_consensus_policy_line,
)
from agent_reach.daily_run.finance_tolerance_policy import (
    finance_tolerance_cfg,
    parse_finance_tolerance_policy_line,
)
from agent_reach.daily_run.harness_policy import apply_harness_policy_overlay
from agent_reach.daily_run.optimizer_grid_policy import (
    optimizer_grid_cfg,
    parse_optimizer_grid_policy_line,
)
from agent_reach.daily_run.watchlist_score_policy import (
    parse_watchlist_score_policy_line,
    watchlist_score_cfg,
)
from agent_reach.daily_run.xueqiu_hit_policy import (
    parse_xueqiu_hit_policy_line,
    xueqiu_hit_threshold_cfg,
)


def test_optimizer_grid_policy_line_parse_and_runtime_cfg():
    line = (
        "optimizer grid最优：macro_veto_low=36 macro_veto_high=46 "
        "aggressive_entry_low=47 aggressive_entry_high=56 grid_points=5 default_objective=excess_return"
    )
    parsed = parse_optimizer_grid_policy_line(line)
    assert parsed
    assert parsed["default_objective"] == "excess_return"
    settings = {
        "optimizer": {"mode": "harness", "default_objective": "sharpe"},
        "harness_runtime": {"optimizer_grid_policy": parsed},
    }
    cfg = optimizer_grid_cfg(settings)
    assert len(cfg["macro_veto_grid"]) == 5
    assert cfg["default_objective"] == "excess_return"


def test_expert_consensus_runtime_cfg():
    settings = {
        "expert_consensus": {"mode": "harness"},
        "harness_runtime": {
            "expert_consensus_policy": {
                "mss_drift_threshold": 10.0,
                "low_score_cutoff": 44.0,
                "high_score_cutoff": 64.0,
                "max_mss_drift_flags": 5.0,
            }
        },
    }
    cfg = expert_consensus_cfg(settings)
    assert cfg["mss_drift_threshold"] == 10.0
    assert cfg["low_score_cutoff"] == 44.0
    parsed = parse_expert_consensus_policy_line(
        "expert_consensus最优：mss_drift_threshold=10 low_score_cutoff=44 high_score_cutoff=64 max_mss_drift_flags=5"
    )
    assert parsed["max_mss_drift_flags"] == 5.0


def test_xueqiu_hit_threshold_runtime_cfg():
    settings = {
        "macro_collector": {"xueqiu_hit_mode": "harness"},
        "harness_runtime": {
            "xueqiu_hit_policy": {
                "xueqiu_hit_low_rate": 0.35,
                "xueqiu_hit_high_rate": 0.65,
                "xueqiu_hit_overlay_min_samples": 4.0,
                "xueqiu_hit_overlay_min_misses": 2.0,
                "xueqiu_hit_overlay_min_hits": 2.0,
            }
        },
    }
    cfg = xueqiu_hit_threshold_cfg(settings)
    assert cfg["xueqiu_hit_low_rate"] == 0.35
    assert cfg["xueqiu_hit_overlay_min_samples"] == 4
    parsed = parse_xueqiu_hit_policy_line(
        "xueqiu_hit最优：xueqiu_hit_low_rate=0.35 xueqiu_hit_high_rate=0.65 "
        "xueqiu_hit_overlay_min_samples=4 xueqiu_hit_overlay_min_misses=2 xueqiu_hit_overlay_min_hits=2"
    )
    assert parsed["xueqiu_hit_high_rate"] == 0.65


def test_data_audit_close_block_evolution(monkeypatch):
    settings = {"data_audit": {"mode": "harness", "close_block_on_audit_fail": False}}

    def _fake_overlay(state, phrase, *, settings):
        return phrase == "数据审计未通过"

    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy._overlay_has_phrase",
        _fake_overlay,
    )
    effective = resolve_harness_data_audit_policy(object(), settings=settings)
    assert effective["close_block_on_audit_fail"] == 1.0
    cfg = data_audit_cfg({**settings, "harness_runtime": {"data_audit_policy": effective}})
    assert cfg["close_block_on_audit_fail"] is True
    parsed = parse_data_audit_policy_line(
        "data_audit最优：min_quote_coverage_pct=0.85 block_on_audit_fail=1 close_block_on_audit_fail=1 block_on_price_deviation=1"
    )
    assert parsed["min_quote_coverage_pct"] == 0.85


def test_finance_tolerance_runtime_cfg():
    settings = {
        "finance_close": {"mode": "harness"},
        "harness_runtime": {
            "finance_tolerance_policy": {
                "reconcile_tolerance_cny": 0.5,
                "variance_tolerance_cny": 4.0,
                "variance_materiality_cny": 800.0,
                "amount_tolerance_cny": 0.8,
                "statement_materiality_cny": 900.0,
                "tie_tolerance_cny": 4.0,
            }
        },
    }
    assert finance_tolerance_cfg(settings)["amount_tolerance_cny"] == 0.8
    parsed = parse_finance_tolerance_policy_line(
        "finance_tolerance最优：reconcile_tolerance_cny=0.5 variance_tolerance_cny=4 "
        "variance_materiality_cny=800 amount_tolerance_cny=0.8 "
        "statement_materiality_cny=900 tie_tolerance_cny=4"
    )
    assert parsed["variance_tolerance_cny"] == 4.0


def test_watchlist_score_runtime_cfg():
    settings = {
        "watchlist": {"mode": "harness"},
        "harness_runtime": {
            "watchlist_score_policy": {
                "announcement_score_boost": 4.0,
                "news_score_boost": 1.5,
                "negative_announcement_penalty": -5.0,
                "negative_news_penalty": -3.0,
                "hot_topic_remove_change_pct": -2.5,
            }
        },
    }
    cfg = watchlist_score_cfg(settings)
    assert cfg["announcement_score_boost"] == 4.0
    assert cfg["negative_announcement_penalty"] == -5.0
    parsed = parse_watchlist_score_policy_line(
        "watchlist_score最优：announcement_score_boost=4 news_score_boost=1.5 "
        "negative_announcement_penalty=-5 negative_news_penalty=-3 hot_topic_remove_change_pct=-2.5"
    )
    assert parsed["news_score_boost"] == 1.5


@patch("agent_reach.daily_run.harness_policy._overlay_enabled", return_value=True)
@patch("agent_reach.daily_run.harness.load_harness", return_value={"memory": [], "policy": []})
def test_apply_harness_policy_overlay_includes_new_policies(mock_load, mock_overlay):
    settings = {
        "harness": {"enabled": True},
        "optimizer": {"mode": "harness"},
        "expert_consensus": {"mode": "harness"},
        "data_audit": {"mode": "harness"},
        "finance_close": {"mode": "harness"},
        "watchlist": {"mode": "harness"},
        "macro_collector": {"xueqiu_hit_mode": "harness"},
        "thresholds": {},
        "experience": {"enabled": True},
    }
    out = apply_harness_policy_overlay(settings)
    runtime = out.get("harness_runtime") or {}
    assert "optimizer_grid_policy" in runtime
    assert "expert_consensus_policy" in runtime
    assert "data_audit_policy" in runtime
    assert "finance_tolerance_policy" in runtime
    assert "watchlist_score_policy" in runtime
    assert "xueqiu_hit_policy" in runtime
    assert out["optimizer"].get("mode") == "harness"
    assert out["watchlist"].get("announcement_score_boost") is not None


def test_fixed_mode_ignores_harness_overlay():
    settings = {
        "optimizer": {"mode": "fixed", "macro_veto_grid": [39, 41], "default_objective": "win_rate"},
        "harness_runtime": {
            "optimizer_grid_policy": {
                "macro_veto_low": 30.0,
                "macro_veto_high": 50.0,
                "default_objective": "sharpe",
            }
        },
    }
    cfg = optimizer_grid_cfg(settings)
    assert cfg["default_objective"] == "win_rate"
    assert cfg["macro_veto_grid"] == [39.0, 41.0]
