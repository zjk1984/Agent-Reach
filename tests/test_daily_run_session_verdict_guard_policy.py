# -*- coding: utf-8
"""Tests for harness-evolved session verdict guards + watchlist drawdown."""

from agent_reach.daily_run.harness import HarnessEntry, HarnessState
from agent_reach.daily_run.session_verdict_guard_policy import (
    parse_session_verdict_policy_line,
    parse_watchlist_drawdown_policy_line,
    resolve_harness_session_verdict_policy,
    resolve_harness_watchlist_drawdown_policy,
    session_verdict_guard_effective_cfg,
    session_verdict_policy_default,
    watchlist_drawdown_effective_cfg,
    watchlist_drawdown_policy_default,
)


def test_session_verdict_effective_cfg_uses_harness_runtime():
    settings = {
        "intraday": {
            "session_verdict_guards": {"mode": "harness", "price_pullback_pct": 2.0},
        },
        "harness_runtime": {
            "session_verdict_policy": {"price_pullback_pct": 1.8, "mss_pullback_pts": 1.7},
        },
    }
    cfg = session_verdict_guard_effective_cfg(settings)
    assert cfg["price_pullback_pct"] == 1.8
    assert cfg["mss_pullback_pts"] == 1.7


def test_watchlist_drawdown_effective_cfg_uses_harness_runtime():
    settings = {
        "intraday": {"watchlist_drawdown": {"mode": "harness", "yellow_pct": -3.0}},
        "harness_runtime": {
            "watchlist_drawdown_policy": {"yellow_pct": -2.5, "red_pct": -4.0},
        },
    }
    cfg = watchlist_drawdown_effective_cfg(settings)
    assert cfg["yellow_pct"] == -2.5
    assert cfg["red_pct"] == -4.0


def test_resolve_session_verdict_tightens_on_pullback_phrase():
    state = HarnessState()
    state.entries["policy"]["pullback"] = HarnessEntry(
        id="pullback",
        kind="policy",
        title="pullback",
        content="盘中 工业富联 冲高回落降级 早盘 S1 可做→观察",
    )
    settings = {
        "harness": {"enabled": True, "runtime_overlay": True},
        "intraday": {"session_verdict_guards": {"mode": "harness"}},
    }
    policy = resolve_harness_session_verdict_policy(state, settings=settings)
    assert policy["price_pullback_pct"] <= 2.0
    assert policy["mss_pullback_pts"] <= 2.0


def test_resolve_watchlist_drawdown_tightens_on_miss_phrase():
    state = HarnessState()
    state.entries["memory"]["miss"] = HarnessEntry(
        id="miss",
        kind="memory",
        title="miss",
        content="海康 观察池 跌幅无预警 暴跌",
    )
    settings = {
        "harness": {"enabled": True, "runtime_overlay": True},
        "intraday": {"watchlist_drawdown": {"mode": "harness"}},
    }
    policy = resolve_harness_watchlist_drawdown_policy(state, settings=settings)
    assert policy["yellow_pct"] >= -3.0
    assert policy["red_pct"] >= -5.0


def test_parse_policy_lines():
    session = parse_session_verdict_policy_line(
        "session_verdict最优：price_pullback_pct=1.80 mss_pullback_pts=1.70"
    )
    assert session is not None
    assert session["price_pullback_pct"] == 1.8
    drawdown = parse_watchlist_drawdown_policy_line(
        "watchlist_drawdown最优：yellow_pct=-2.50 red_pct=-4.00"
    )
    assert drawdown is not None
    assert drawdown["yellow_pct"] == -2.5


def test_policy_defaults_without_overlay():
    settings = {
        "intraday": {
            "session_verdict_guards": {"mode": "fixed", "price_pullback_pct": 2.5},
            "watchlist_drawdown": {"mode": "fixed", "yellow_pct": -2.0, "red_pct": -4.0},
        }
    }
    assert session_verdict_policy_default(settings, "price_pullback_pct") == 2.5
    assert watchlist_drawdown_policy_default(settings, "yellow_pct") == -2.0
