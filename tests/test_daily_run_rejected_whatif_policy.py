# -*- coding: utf-8
"""Tests for harness-evolved rejected weekly_whatif policy."""

from agent_reach.daily_run.rejected_whatif_policy import (
    format_weekly_whatif_policy_line,
    parse_weekly_whatif_policy_line,
    resolve_harness_weekly_whatif_policy,
    weekly_whatif_cfg,
    weekly_whatif_policy_base,
)


def test_weekly_whatif_cfg_uses_harness_policy():
    settings = {
        "rejected_strategies": {
            "weekly_whatif": {"mode": "harness", "buy_notional_delta_cny": 5000},
        },
        "harness_runtime": {
            "weekly_whatif_policy": {
                "buy_notional_delta_cny": 6500.0,
                "sell_pnl_delta_cny": 200.0,
                "friction_pass_min": 3.0,
                "trend_mismatch_min": 2.0,
                "intraday_sell_missed_min": 2.0,
                "deep_loss_lag_count_min": 1.0,
                "deep_loss_share_delta_min": 100.0,
                "sell_threshold_missed_min": 2.0,
                "forecast_divergence_days_min": 3.0,
                "optimizer_score_delta_min": 0.05,
                "kronos_blocked_signals_min": 2.0,
            }
        },
    }
    cfg = weekly_whatif_cfg(settings)
    assert cfg["buy_notional_delta_cny"] == 6500.0
    assert cfg["friction_pass_min"] == 3


def test_parse_and_apply_weekly_whatif_policy_line():
    line = format_weekly_whatif_policy_line(weekly_whatif_policy_base({}), rationale="test")
    assert line.startswith("rejected weekly_whatif最优：")
    parsed = parse_weekly_whatif_policy_line(line)
    assert parsed is not None
    assert parsed["buy_notional_delta_cny"] == 5000.0


def test_signal_evolution_tightens_on_profit_week_adds(monkeypatch):
    settings = {
        "rejected_strategies": {"weekly_whatif": {"mode": "harness"}},
        "harness": {"runtime_overlay": True},
    }

    def _fake_overlay(state, phrase, *, settings):
        return phrase == "盈利周证伪库仍入库"

    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy._overlay_has_phrase",
        _fake_overlay,
    )
    resolved = resolve_harness_weekly_whatif_policy(object(), settings=settings)
    base = weekly_whatif_policy_base(settings)
    assert resolved["buy_notional_delta_cny"] > base["buy_notional_delta_cny"]
    assert resolved["friction_pass_min"] >= base["friction_pass_min"]


def test_fixed_mode_ignores_harness_overlay():
    settings = {
        "rejected_strategies": {
            "weekly_whatif": {"mode": "fixed", "buy_notional_delta_cny": 4200},
        },
        "harness_runtime": {
            "weekly_whatif_policy": {"buy_notional_delta_cny": 9000.0},
        },
    }
    cfg = weekly_whatif_cfg(settings)
    assert cfg["buy_notional_delta_cny"] == 4200.0
