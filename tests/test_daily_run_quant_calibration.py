# -*- coding: utf-8
"""Tests for cross-day quant calibration (session seed, walk-forward, friction)."""

from datetime import date
from unittest.mock import patch

from agent_reach.daily_run.quant_calibration import (
    build_next_day_session_seed,
    classify_close_session_regime,
    effective_overlay_deltas,
    friction_buy_blocked,
    merge_session_regime,
    recommend_overlay_deltas,
    rolling_buy_mtm_gate,
    walkforward_report,
)


def _cfg() -> dict:
    return {
        "loss_pct_defensive": -0.15,
        "supportive_pnl_pct": 0.1,
    }


def test_classify_close_session_regime_defensive_on_loss():
    regime, reasons = classify_close_session_regime(
        daily_pnl=-500.0,
        daily_pnl_pct=-0.43,
        defensive_trim=False,
        cfg=_cfg(),
    )
    assert regime == "defensive"
    assert reasons


def test_merge_session_regime_defensive_wins():
    assert merge_session_regime("supportive", "defensive") == "defensive"
    assert merge_session_regime("neutral", "supportive") == "supportive"
    assert merge_session_regime("defensive", "supportive") == "defensive"


def test_build_next_day_session_seed_includes_regime():
    seed = build_next_day_session_seed(
        portfolio_summary={"daily_pnl": -100.0, "daily_pnl_pct": -0.2},
        settings={"quant_calibration": {"enabled": True}},
    )
    assert seed["regime"] == "defensive"
    assert seed["enabled"] is True
    assert "overlay_recommendation" in seed


def test_effective_overlay_deltas_applies_walkforward_recommendation():
    settings = {
        "morning_open": {"aggressive_entry_delta": 2.0, "macro_veto_delta": 2.0},
        "quant_calibration": {"enabled": True, "apply_walkforward_overlay": True},
    }
    seed = {
        "enabled": True,
        "overlay_recommendation": {
            "morning_open": {
                "aggressive_entry_delta": 4.0,
                "macro_veto_delta": 3.5,
                "trade_every_n_delta": 2,
            }
        },
    }
    with patch(
        "agent_reach.daily_run.quant_calibration.load_prior_close_session_seed",
        return_value=seed,
    ):
        deltas = effective_overlay_deltas("morning_open", settings)
    assert deltas["aggressive_entry_delta"] == 4.0
    assert deltas["macro_veto_delta"] == 3.5
    assert deltas["trade_every_n_delta"] == 2


def test_rolling_buy_mtm_gate_blocks_when_sum_below_threshold():
    settings = {
        "quant_calibration": {
            "enabled": True,
            "rolling_mtm_gate_enabled": True,
            "rolling_mtm_min_sum": 0.0,
        }
    }
    seed = {"rolling": {"mtm_sum": -200.0, "window_days": 5}}
    with patch(
        "agent_reach.daily_run.quant_calibration.load_prior_close_session_seed",
        return_value=seed,
    ):
        ok, detail = rolling_buy_mtm_gate(settings=settings)
    assert ok is False
    assert "MTM" in detail


def test_friction_buy_blocked_with_multiplier():
    settings = {
        "quant_calibration": {
            "friction_block_buys": True,
            "friction_buy_multiplier": 1.25,
        },
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001},
    }
    with patch(
        "agent_reach.daily_run.intraday_policy.effective_friction_hurdle",
        return_value=0.004,
    ):
        assert friction_buy_blocked(0.004, settings) is True
        assert friction_buy_blocked(0.006, settings) is False


def test_recommend_overlay_deltas_after_loss_streak():
    history = [
        {"next_day_session_seed": {"daily_pnl": -100, "buy_whatif": {"baseline_excess_buy_mtm_pnl": -50}}},
        {"next_day_session_seed": {"daily_pnl": -200, "buy_whatif": {"baseline_excess_buy_mtm_pnl": -30}}},
        {"next_day_session_seed": {"daily_pnl": -50, "buy_whatif": {"baseline_excess_buy_mtm_pnl": 10}}},
    ]
    rec = recommend_overlay_deltas(history, cfg={"walkforward_window_days": 10})
    assert rec["morning_open"]["aggressive_entry_delta"] >= 3.0


def test_walkforward_report_structure():
    with patch(
        "agent_reach.daily_run.quant_calibration.load_close_handoff_history",
        return_value=[],
    ):
        report = walkforward_report(settings={"quant_calibration": {"enabled": True}})
    assert "rolling" in report
    assert "effective_morning_open" in report


def test_forecast_hit_rate_gate_blocks_low_hit_rate():
    settings = {
        "quant_calibration": {
            "enabled": True,
            "forecast_hit_rate_gate_enabled": True,
            "forecast_hit_rate_min": 0.45,
        }
    }
    with patch(
        "agent_reach.daily_run.week_forecast.load_calibration_file",
        return_value={"hit_rate": 0.3},
    ):
        from agent_reach.daily_run.quant_calibration import forecast_hit_rate_gate

        ok, detail = forecast_hit_rate_gate(settings=settings)
    assert ok is False
    assert "命中率" in detail


def test_forecast_to_harness_includes_walkforward():
    from agent_reach.daily_run.forecast_calibrate_harness import forecast_to_harness_evidence

    with patch(
        "agent_reach.daily_run.quant_calibration.walkforward_report",
        return_value={
            "overlay_recommendation": {
                "basis": {"loss_days": 2, "pnl_sum": -100, "mtm_sum": -50},
                "morning_open": {"aggressive_entry_delta": 3.0},
            }
        },
    ):
        evidence = forecast_to_harness_evidence({"week_start": "2026-09-07"}, settings={})
    assert any("walk-forward" in line for line in evidence["memory"])


def test_close_handoff_carries_session_seed(tmp_path, monkeypatch):
    from agent_reach.daily_run.close_morning_handoff import build_close_handoff, save_close_handoff

    monkeypatch.setattr(
        "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.quant_calibration.load_close_handoff_history",
        lambda **kwargs: [],
    )

    from tests.test_daily_run_close_morning_handoff import CLOSE_CTX

    payload = build_close_handoff(CLOSE_CTX)
    payload["close_date"] = date(2026, 8, 28).isoformat()
    save_close_handoff(payload)
    assert payload["next_day_session_seed"]["regime"] in {"defensive", "neutral", "supportive"}
