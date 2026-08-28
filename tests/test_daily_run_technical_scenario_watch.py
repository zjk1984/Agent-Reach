# -*- coding: utf-8
"""Tests for upper-shadow technical scenario watch."""

from datetime import date

import pytest

from agent_reach.daily_run.technical_scenario_watch import (
    evaluate_scenario,
    format_close_technical_watch_markdown,
    format_technical_scenario_markdown,
    load_scenarios,
    maybe_register_limit_up_shrink_pullback_from_session,
    maybe_register_upper_shadow_from_session,
    register_limit_up_shrink_pullback_scenario,
    register_upper_shadow_scenario,
    run_close_technical_watch,
    save_scenarios,
    scenarios_for_setup_date,
    technical_scenario_harness_evidence,
)


@pytest.fixture
def scenario_path(tmp_path):
    return tmp_path / "technical_scenarios.json"


def test_register_upper_shadow_scenario(scenario_path):
    row = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["session_low"] == 856.63
    assert row["eval_from"] == "2026-08-31"
    saved = load_scenarios(scenario_path)
    assert len(saved) == 1
    assert saved[0]["scenario_type"] == "upper_shadow"


def test_evaluate_bearish_break_below_low(scenario_path):
    scenario = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=855.0, change_pct=-1.2)
    assert result["status"] == "bearish_confirmed"
    assert "见顶" in result["headline"]


def test_evaluate_bullish_reclaim_high(scenario_path):
    scenario = register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=916.0, change_pct=6.5, open_price=870.0)
    assert result["status"] == "bullish_washout"
    assert "洗盘" in result["headline"]


def test_harness_writes_sell_late_on_bearish_confirm(scenario_path, monkeypatch):
    register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 31),
    )
    from agent_reach.daily_run.technical_scenario_watch import evaluate_active_scenarios

    evals = evaluate_active_scenarios(
        {"code": "300308", "price": 850.0, "change_pct": -2.0},
        as_of=date(2026, 8, 31),
        path=scenario_path,
    )
    lines = technical_scenario_harness_evidence(evals, path=scenario_path)
    assert any("卖晚了" in item for item in lines["memory"])
    assert load_scenarios(scenario_path)[0]["status"] == "bearish_confirmed"


def test_maybe_register_from_session(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    row = maybe_register_upper_shadow_from_session(
        code="300308",
        name="中际旭创",
        snapshot={
            "code": "300308",
            "price": 858.35,
            "change_pct": 5.74,
            "day_high": 915.88,
            "day_low": 856.63,
        },
        session_scans=[{"code": "300308", "price": 896.74}],
        path=scenario_path,
    )
    assert row is not None
    assert load_scenarios(scenario_path)[0]["session_high"] == 915.88


def test_format_markdown():
    md = format_technical_scenario_markdown(
        [{"headline": "中际旭创 长上影后续：跌破 856.63 确认短期见顶"}]
    )
    assert "技术情景跟踪" in md
    assert "856.63" in md


def test_format_close_technical_watch_markdown():
    md = format_close_technical_watch_markdown(
        [
            {
                "code": "300308",
                "name": "中际旭创",
                "setup_date": "2026-08-28",
                "session_high": 915.88,
                "session_close": 858.35,
                "session_low": 856.63,
                "eval_from": "2026-08-31",
                "bearish": {"label": "低开低走跌破今日低点，确认短期见顶"},
                "bullish": {"label": "高开反包则上影线为洗盘"},
            }
        ]
    )
    assert "收盘登记" in md
    assert "915.88" in md
    assert "856.63" in md
    assert "2026-08-31" in md


def test_scenarios_for_setup_date(scenario_path):
    register_upper_shadow_scenario(
        code="300308",
        name="中际旭创",
        setup_date="2026-08-28",
        session_high=915.88,
        session_close=858.35,
        session_low=856.63,
        path=scenario_path,
    )
    rows = scenarios_for_setup_date("2026-08-28", path=scenario_path)
    assert len(rows) == 1
    assert rows[0]["code"] == "300308"


def test_run_close_technical_watch_registers_and_renders(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )

    def _fake_quotes(codes, settings=None):
        from agent_reach.daily_run.quote_fetch import QuoteFetchResult

        return QuoteFetchResult(
            quotes={
                "300308": {
                    "code": "300308",
                    "name": "中际旭创",
                    "price": 858.35,
                    "change_pct": 5.74,
                    "day_high": 915.88,
                    "day_low": 856.63,
                }
            }
        )

    monkeypatch.setattr(
        "agent_reach.daily_run.quote_fetch.fetch_quotes_map",
        _fake_quotes,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.load_state",
        lambda **kwargs: type("S", (), {"scans": [{"code": "300308", "price": 896.74}]})(),
    )

    snapshot = {
        "code": "688008",
        "portfolio": {
            "holdings": [],
            "watchlist": [{"code": "300308", "name": "中际旭创"}],
        },
        "watchlist": [{"code": "300308", "name": "中际旭创"}],
    }
    result = run_close_technical_watch(
        snapshot,
        settings={"technical_watch": {"enabled": True}, "trade_calendar": {}},
        path=scenario_path,
    )
    assert result["registered"]
    assert "915.88" in result["markdown"]
    assert "856.63" in result["markdown"]


def test_register_limit_up_shrink_pullback(scenario_path):
    row = register_limit_up_shrink_pullback_scenario(
        code="688008",
        name="澜起科技",
        setup_date="2026-08-28",
        prior_close=221.22,
        session_close=213.0,
        session_low=213.0,
        session_high=221.49,
        support_level=210.0,
        prior_day_change_pct=20.0,
        volume_ratio=0.62,
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["support_level"] == 210.0
    assert row["scenario_type"] == "limit_up_shrink_pullback"
    saved = load_scenarios(scenario_path)
    assert len(saved) == 1


def test_evaluate_shrink_pullback_support_holding(scenario_path):
    scenario = register_limit_up_shrink_pullback_scenario(
        code="688008",
        name="澜起科技",
        setup_date="2026-08-28",
        prior_close=221.22,
        session_close=213.0,
        session_low=213.0,
        session_high=221.49,
        support_level=210.0,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=211.0, change_pct=-0.5, volume_ratio=0.7)
    assert result["status"] == "support_holding"
    assert "210" in result["headline"]


def test_evaluate_shrink_pullback_adjustment_open(scenario_path):
    scenario = register_limit_up_shrink_pullback_scenario(
        code="688008",
        name="澜起科技",
        setup_date="2026-08-28",
        prior_close=221.22,
        session_close=213.0,
        session_low=213.0,
        session_high=221.49,
        support_level=210.0,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, price=203.0, change_pct=-3.0, volume_ratio=1.3)
    assert result["status"] == "adjustment_open"
    assert "调整空间" in result["headline"]


def test_maybe_register_shrink_pullback_from_session(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    row = maybe_register_limit_up_shrink_pullback_from_session(
        code="688008",
        name="澜起科技",
        snapshot={
            "code": "688008",
            "price": 213.0,
            "change_pct": -3.72,
            "reference_price": 221.22,
            "volume_ratio": 0.62,
            "day_high": 221.49,
            "day_low": 213.0,
            "prior_day_change_pct": 20.0,
        },
        session_scans=[{"code": "688008", "price": 221.22}],
        path=scenario_path,
        settings={"technical_watch": {"enabled": True}, "trade_calendar": {}},
    )
    assert row is not None
    assert load_scenarios(scenario_path)[0]["support_level"] == 210.0


def test_format_close_markdown_includes_shrink_pullback():
    md = format_close_technical_watch_markdown(
        [
            {
                "scenario_type": "limit_up_shrink_pullback",
                "code": "688008",
                "name": "澜起科技",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "prior_close": 221.22,
                "session_close": 213.0,
                "session_low": 213.0,
                "support_level": 210.0,
                "bullish": {"label": "在 210 元附近缩量企稳"},
                "bearish": {"label": "继续放量下跌，调整空间打开"},
            }
        ]
    )
    assert "澜起科技" in md
    assert "210" in md
    assert "缩量回调" in md
