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
    maybe_register_liquidity_shrink_from_session,
    maybe_register_upper_shadow_from_session,
    register_limit_up_shrink_pullback_scenario,
    register_liquidity_shrink_scenario,
    register_mss_trend_scenario,
    register_min_cash_ratio_cap_scenario,
    register_upper_shadow_scenario,
    collect_scan_mss_range,
    maybe_register_mss_trend_from_session,
    maybe_register_min_cash_ratio_cap_from_session,
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


def test_register_liquidity_shrink(scenario_path):
    row = register_liquidity_shrink_scenario(
        code="002583",
        name="海能达",
        setup_date="2026-08-28",
        session_close=8.44,
        session_low=8.43,
        turnover=128_912_859.44,
        turnover_rate=1.18,
        volume_ratio=0.62,
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["scenario_type"] == "liquidity_shrink"
    assert row["setup_turnover"] == 128912859.44


def test_evaluate_liquidity_trim_risk(scenario_path):
    scenario = register_liquidity_shrink_scenario(
        code="002583",
        name="海能达",
        setup_date="2026-08-28",
        session_close=8.44,
        session_low=8.43,
        turnover=128_912_859.44,
        path=scenario_path,
    )
    result = evaluate_scenario(
        scenario,
        price=8.2,
        change_pct=-2.0,
        turnover=100_000_000.0,
    )
    assert result["status"] == "liquidity_trim_risk"
    assert "减仓" in result["headline"]


def test_evaluate_liquidity_recovered(scenario_path):
    scenario = register_liquidity_shrink_scenario(
        code="002583",
        name="海能达",
        setup_date="2026-08-28",
        session_close=8.44,
        session_low=8.43,
        turnover=128_912_859.44,
        path=scenario_path,
    )
    result = evaluate_scenario(
        scenario,
        price=8.5,
        change_pct=0.5,
        turnover=200_000_000.0,
        volume_ratio=1.2,
    )
    assert result["status"] == "liquidity_recovered"


def test_maybe_register_liquidity_shrink(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    row = maybe_register_liquidity_shrink_from_session(
        code="002583",
        name="海能达",
        snapshot={
            "code": "002583",
            "price": 8.44,
            "change_pct": -1.4,
            "turnover": 128_912_859.44,
            "turnover_rate": 1.18,
            "volume_ratio": 0.62,
            "day_low": 8.43,
        },
        path=scenario_path,
        settings={"technical_watch": {"enabled": True}, "trade_calendar": {}},
    )
    assert row is not None
    assert "1.29亿" in row["note"] or "成交额" in row["note"]


def test_format_close_markdown_includes_liquidity_shrink():
    md = format_close_technical_watch_markdown(
        [
            {
                "scenario_type": "liquidity_shrink",
                "code": "002583",
                "name": "海能达",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "session_close": 8.44,
                "session_low": 8.43,
                "setup_turnover": 128912859.44,
                "setup_turnover_rate": 1.18,
                "bullish": {"label": "成交额恢复且排查无基本面恶化"},
                "bearish": {"label": "流动性持续萎缩，关注被进一步减仓"},
            }
        ]
    )
    assert "海能达" in md
    assert "1.29亿" in md
    assert "流动性" in md


def test_register_mss_trend(scenario_path):
    row = register_mss_trend_scenario(
        setup_date="2026-08-28",
        mss_low=49.62,
        mss_high=51.62,
        mss_scan_id="S12",
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["scenario_type"] == "mss_trend"
    assert row["code"] == "SYSTEM"
    assert row["setup_mss_low"] == 49.62


def test_evaluate_mss_deeper_defense(scenario_path):
    scenario = register_mss_trend_scenario(
        setup_date="2026-08-28",
        mss_low=49.6,
        mss_high=51.6,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, mss=44.0)
    assert result["status"] == "deeper_defense"
    assert "深层防御" in result["headline"]


def test_evaluate_mss_defense_released(scenario_path):
    scenario = register_mss_trend_scenario(
        setup_date="2026-08-28",
        mss_low=49.6,
        mss_high=51.6,
        path=scenario_path,
    )
    result = evaluate_scenario(scenario, mss=56.0)
    assert result["status"] == "defense_released"


def test_format_close_markdown_includes_mss_trend():
    md = format_close_technical_watch_markdown(
        [
            {
                "scenario_type": "mss_trend",
                "code": "SYSTEM",
                "name": "量化系统MSS",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "mss_scan_id": "S12",
                "setup_mss_low": 49.6,
                "setup_mss_high": 51.6,
                "warning_level": 50.0,
                "bearish": {"label": "MSS 继续下行至 45 以下，触发更深层防御"},
                "bullish": {"label": "MSS 反弹回 55 以上，防御解除"},
            }
        ]
    )
    assert "量化系统MSS" in md
    assert "49.6" in md
    assert "深层防御" in md


def test_maybe_register_mss_trend(scenario_path, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    intraday_dir = tmp_path / "intraday"
    intraday_dir.mkdir()
    for code, mss in (("688008", 51.62), ("002273", 49.81), ("002583", 51.41)):
        payload = {
            "date": "2026-08-28",
            "scans": [{"scan_id": "S12", "code": code, "mss_final": mss}],
            "trades": [],
        }
        (intraday_dir / f"{code}.json").write_text(
            __import__("json").dumps(payload),
            encoding="utf-8",
        )

    def _state_path(code=None):
        norm = code or ""
        return intraday_dir / f"{norm}.json"

    monkeypatch.setattr(
        "agent_reach.daily_run.intraday._today_str",
        lambda: "2026-08-28",
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.intraday.default_state_path",
        _state_path,
    )

    row = maybe_register_mss_trend_from_session(
        symbols=["688008", "002273", "002583"],
        path=scenario_path,
        settings={
            "technical_watch": {"enabled": True, "mss_trend": {"scope": "holdings"}},
            "trade_calendar": {},
        },
    )
    assert row is not None
    assert row["setup_mss_low"] == 49.81
    assert row["setup_mss_high"] == 51.62


def test_register_min_cash_ratio_cap(scenario_path):
    row = register_min_cash_ratio_cap_scenario(
        setup_date="2026-08-28",
        min_cash_ratio=0.5,
        cash_ratio=0.4867,
        baseline_min_cash_ratio=0.0,
        path=scenario_path,
        settings={"trade_calendar": {}},
    )
    assert row["scenario_type"] == "min_cash_ratio_cap"
    assert row["setup_min_cash_ratio"] == 0.5


def test_evaluate_min_cash_threshold_relaxed(scenario_path):
    scenario = register_min_cash_ratio_cap_scenario(
        setup_date="2026-08-28",
        min_cash_ratio=0.5,
        cash_ratio=0.49,
        path=scenario_path,
    )
    result = evaluate_scenario(
        scenario,
        min_cash_ratio=0.45,
        cash_ratio=0.49,
        mss=56.0,
    )
    assert result["status"] == "threshold_relaxed"
    assert "回调" in result["headline"]


def test_evaluate_min_cash_rally_miss_risk(scenario_path):
    scenario = register_min_cash_ratio_cap_scenario(
        setup_date="2026-08-28",
        min_cash_ratio=0.5,
        cash_ratio=0.487,
        path=scenario_path,
    )
    result = evaluate_scenario(
        scenario,
        min_cash_ratio=0.5,
        cash_ratio=0.487,
        mss=56.0,
    )
    assert result["status"] == "rally_miss_risk"
    assert "踏空" in result["headline"]


def test_maybe_register_min_cash_cap(scenario_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.technical_scenario_watch.today_shanghai",
        lambda: date(2026, 8, 28),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy.min_cash_ratio_default",
        lambda settings: 0.5,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy.min_cash_ratio_base",
        lambda settings, thresholds: 0.0,
    )
    row = maybe_register_min_cash_ratio_cap_from_session(
        {
            "portfolio": {"cash_ratio": 0.4867, "holdings": [], "watchlist": []},
        },
        path=scenario_path,
        settings={
            "technical_watch": {"enabled": True},
            "thresholds": {},
            "trade_calendar": {},
        },
    )
    assert row is not None
    assert row["setup_cash_ratio"] == 0.4867


def test_format_close_markdown_includes_min_cash_cap():
    md = format_close_technical_watch_markdown(
        [
            {
                "scenario_type": "min_cash_ratio_cap",
                "code": "SYSTEM",
                "name": "量化系统现金比例",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "setup_min_cash_ratio": 0.5,
                "setup_cash_ratio": 0.4867,
                "baseline_min_cash_ratio": 0.0,
                "bullish": {"label": "harness 回调 min_cash 阈值后可加仓"},
                "bearish": {"label": "市场反弹时现金比例限制可能踏空"},
            }
        ]
    )
    assert "min_cash" in md
    assert "50%" in md or "0.5" in md.lower()


def test_default_support_level_mid_and_low_cap():
    from agent_reach.daily_run.technical_scenario_watch import (
        _default_support_level,
        _normalize_support_level,
        _resolve_scenario_support,
        _support_stabilize_label,
    )

    assert _default_support_level(26.1) == 26.0
    assert _default_support_level(8.43) == 8.0
    assert _default_support_level(213.0) == 210.0
    assert _normalize_support_level(26.1, 26.12, 20.0) == 26.0
    assert _normalize_support_level(8.43, 8.44, 0.0) == 8.0
    assert _support_stabilize_label(8.0) == "在 8 元附近缩量企稳"
    assert _support_stabilize_label(26.0) == "在 26 元附近缩量企稳"

    scenario = {
        "scenario_type": "limit_up_shrink_pullback",
        "session_low": 26.1,
        "session_close": 26.12,
        "support_level": 20.0,
        "bullish": {"level": 20.0, "label": "在 20 元附近缩量企稳"},
    }
    assert _resolve_scenario_support(scenario) == 26.0


def test_format_close_markdown_uses_correct_support(scenario_path):
    from agent_reach.daily_run.technical_scenario_watch import format_close_technical_watch_markdown

    save_scenarios(
        [
            {
                "scenario_type": "limit_up_shrink_pullback",
                "code": "002273",
                "name": "水晶光电",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "prior_close": 26.81,
                "session_close": 26.12,
                "session_low": 26.1,
                "support_level": 20.0,
                "bullish": {"level": 20.0, "label": "在 20 元附近缩量企稳"},
                "bearish": {"label": "继续放量下跌，调整空间打开"},
            },
            {
                "scenario_type": "limit_up_shrink_pullback",
                "code": "002583",
                "name": "海能达",
                "setup_date": "2026-08-28",
                "eval_from": "2026-08-31",
                "prior_close": 8.56,
                "session_close": 8.44,
                "session_low": 8.43,
                "support_level": 0.0,
                "bullish": {"level": 0.0, "label": "在 0 元附近缩量企稳"},
                "bearish": {"label": "继续放量下跌，调整空间打开"},
            },
        ],
        scenario_path,
    )
    md = format_close_technical_watch_markdown(load_scenarios(scenario_path))
    assert "在 26 元附近缩量企稳" in md
    assert "在 20 元附近缩量企稳" not in md
    assert "在 8 元附近缩量企稳" in md
    assert "0 元" not in md
