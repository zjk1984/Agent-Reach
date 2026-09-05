# -*- coding: utf-8
"""Tests for Sunday 持有 plan two-strike defensive_trim debounce."""

import pytest

from agent_reach.daily_run.hold_debounce_guards import (
    operation_plan_requires_hold_debounce,
    touch_week_open_hold_debounce,
)
from agent_reach.daily_run.intraday import _decide_trade
from agent_reach.daily_run.verdict import VerdictResult


def _week_open_overlay(operation_plan: str) -> dict:
    return {
        "enabled": True,
        "operation_plans": [
            {
                "code": "000725",
                "operation_plan": operation_plan,
                "confidence_pct": 55,
            }
        ],
    }


def _week_open_settings(*, operation_plan: str) -> dict:
    return {
        "thresholds": {"macro_veto": 30, "aggressive_entry": 45, "min_cash_ratio": 0.5},
        "trading": {"commission_rate": 0.0015, "slippage_rate": 0.001, "holding_lock_days": 1},
        "intraday": {
            "trend_min_points": 2,
            "defensive_trim": {
                "hold_debounce": {"enabled": True},
            },
        },
        "harness_runtime": {
            "week_open": {"active": True, "regime": "defensive"},
            "hold_debounce_policy": {"required_strikes": 2.0, "hold_sell_ratio_cap": 0.15},
            "trade_signals": {"defensive_trim": True, "mss_forecast_miss": True},
            "trend_policy": {"sell_trends": ["falling", "turning_down", "mixed"]},
            "deep_loss_policy": {
                "loss_cny_threshold": 5000,
                "loss_pct_threshold": 10,
                "cover_ratio": 0.0,
                "sell_ratio": 0.5,
                "non_deep_loss_sell_ratio": 0.7,
            },
        },
    }


@pytest.fixture
def patch_week_open_overlay(monkeypatch):
    overlay: dict = {}

    def _set(plan: str) -> None:
        overlay.clear()
        overlay.update(_week_open_overlay(plan))

    def _load(*, as_of=None):
        return dict(overlay) if overlay else None

    monkeypatch.setattr(
        "agent_reach.daily_run.week_open_overlay.load_week_open_overlay",
        _load,
    )
    return _set


def _decide_with_strikes(settings: dict, *, strikes: dict[str, int], lookback_mss: float = 49.0):
    verdict = VerdictResult(
        verdict="观察",
        confidence="中",
        mss_final=lookback_mss,
        entry_price=None,
        stop_loss_price=None,
        invalidation="",
        reasoning="",
        blocked=False,
    )
    return _decide_trade(
        lookback_mss=lookback_mss,
        trend="turning_down",
        verdict=verdict,
        report={"code": "000725", "name": "京东方Ａ", "blocked": False},
        snapshot={
            "portfolio": {
                "cash_ratio": 0.6,
                "holdings": [
                    {
                        "code": "000725",
                        "name": "京东方Ａ",
                        "shares": 3900,
                        "cost": 5.74,
                        "price": 5.92,
                        "days_held": 2,
                    }
                ],
            },
            "symbols": [{"code": "000725", "price": 5.92}],
        },
        settings=settings,
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
        hold_debounce_strikes=strikes,
    )


def test_operation_plan_requires_hold_debounce(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    assert operation_plan_requires_hold_debounce("000725", settings) is True

    patch_week_open_overlay("减仓：跌破支撑 → 目标 10%")
    trim_settings = _week_open_settings(operation_plan="减仓：跌破支撑 → 目标 10%")
    assert operation_plan_requires_hold_debounce("000725", trim_settings) is False


def test_touch_hold_debounce_blocks_first_two_strikes(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    strikes: dict[str, int] = {}

    block1, cap1 = touch_week_open_hold_debounce(
        settings, "000725", allow_defensive=True, strikes=strikes
    )
    assert block1 is not None
    assert cap1 is None
    assert strikes["000725"] == 1

    block2, cap2 = touch_week_open_hold_debounce(
        settings, "000725", allow_defensive=True, strikes=strikes
    )
    assert block2 is not None
    assert cap2 is None
    assert strikes["000725"] == 2

    block3, cap3 = touch_week_open_hold_debounce(
        settings, "000725", allow_defensive=True, strikes=strikes
    )
    assert block3 is None
    assert cap3 == 0.15


def test_touch_resets_strikes_when_defensive_trim_not_allowed(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    strikes = {"000725": 1}

    block, cap = touch_week_open_hold_debounce(
        settings, "000725", allow_defensive=False, strikes=strikes
    )
    assert block is None
    assert cap is None
    assert strikes["000725"] == 0


def test_decide_trade_blocks_first_strike_for_hold_plan(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    strikes: dict[str, int] = {}

    decision = _decide_with_strikes(settings, strikes=strikes)
    assert decision.action == "hold"
    assert decision.block_kind == "sell_week_open_hold_debounce"
    assert strikes["000725"] == 1


def test_decide_trade_allows_sell_on_third_strike_with_cap(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    strikes = {"000725": 2}

    decision = _decide_with_strikes(settings, strikes=strikes)
    assert decision.action == "sell"
    assert decision.sell_kind == "defensive_trim"
    assert decision.sell_ratio_override == 0.15


def test_trim_plan_keeps_single_shot_defensive_trim(patch_week_open_overlay):
    patch_week_open_overlay("减仓：跌破支撑 → 目标 10%")
    settings = _week_open_settings(operation_plan="减仓：跌破支撑 → 目标 10%")
    strikes: dict[str, int] = {}

    decision = _decide_with_strikes(settings, strikes=strikes)
    assert decision.action == "sell"
    assert decision.block_kind is None
    assert strikes == {}


def test_decide_trade_skips_hold_debounce_for_watchlist_zero_position(patch_week_open_overlay):
    patch_week_open_overlay("持有：— → 目标 维持2%；止损 5元")
    settings = _week_open_settings(operation_plan="持有：— → 目标 维持2%；止损 5元")
    strikes = {"601138": 3}
    verdict = VerdictResult(
        verdict="观察",
        confidence="中",
        mss_final=49.0,
        entry_price=None,
        stop_loss_price=None,
        invalidation="",
        reasoning="",
        blocked=False,
    )

    decision = _decide_trade(
        lookback_mss=49.0,
        trend="turning_down",
        verdict=verdict,
        report={"code": "601138", "name": "工业富联", "blocked": False},
        snapshot={
            "portfolio": {
                "cash_ratio": 0.6,
                "holdings": [
                    {
                        "code": "000725",
                        "name": "京东方Ａ",
                        "shares": 3900,
                        "cost": 5.74,
                        "price": 5.92,
                        "days_held": 2,
                    }
                ],
            },
            "symbols": [{"code": "601138", "price": 24.5}],
        },
        settings=settings,
        trade_index=1,
        expected_return_pct=0.01,
        prior_trades=[],
        hold_debounce_strikes=strikes,
    )

    assert decision.action == "hold"
    assert decision.block_kind is None
    assert decision.blocked is False
    assert strikes["601138"] == 0


def test_harness_evolution_tightens_debounce_on_premature_trim_memory(monkeypatch):
    from agent_reach.daily_run.harness import HarnessEntry, HarnessState
    from agent_reach.daily_run.harness_policy import (
        apply_harness_policy_overlay,
        resolve_harness_hold_debounce_policy,
    )

    state = HarnessState()
    state.entries["memory"]["hold_conflict"] = HarnessEntry(
        id="hold_conflict",
        kind="memory",
        title="000725 持有计划冲突",
        content="000725 周日计划持有但 defensive_trim 卖早了，应加强 debounce",
        source="deterministic",
        job="close",
        evidence="trade",
        created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
    )
    monkeypatch.setattr("agent_reach.daily_run.harness.load_harness", lambda: state)

    settings = {
        "thresholds": {"max_snapshot_age_hours": 24},
        "harness": {"enabled": True, "runtime_overlay": True},
        "intraday": {"defensive_trim": {"hold_debounce": {"enabled": True}}},
    }
    effective = resolve_harness_hold_debounce_policy(state, settings=settings)
    assert effective["required_strikes"] >= 3.0
    assert effective["hold_sell_ratio_cap"] <= 0.12

    cfg = apply_harness_policy_overlay(settings)
    runtime_policy = (cfg.get("harness_runtime") or {}).get("hold_debounce_policy") or {}
    assert runtime_policy.get("required_strikes", 0) >= 3.0
    injected = (
        ((cfg.get("intraday") or {}).get("defensive_trim") or {}).get("hold_debounce") or {}
    )
    assert injected.get("required_strikes", 0) >= 3
