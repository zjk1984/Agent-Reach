# -*- coding: utf-8 -*-
"""Comprehensive unit tests for TSP intraday quant integration."""

import time
import pytest
from unittest.mock import patch

from agent_reach.daily_run.tsp.config import tsp_quant_cfg
from agent_reach.daily_run.tsp.intraday_sentinel import (
    TSPMainlineMatch,
    check_intraday_retreat_risk,
    clear_intraday_sentinel_cache,
    format_tsp_intraday_card_markdown,
    get_live_market_breadth_and_phase,
    is_symbol_in_top_n_mainlines,
    match_symbol_tsp_mainline,
)
from agent_reach.daily_run.intraday import (
    TRADE_BLOCK_MESSAGES,
    _decide_trade,
    format_trade_block_message,
    infer_trade_block_kind,
    render_intraday_scan_markdown,
)


@pytest.fixture(autouse=True)
def reset_tsp_cache():
    clear_intraday_sentinel_cache()
    yield
    clear_intraday_sentinel_cache()


def test_tsp_intraday_config():
    cfg = tsp_quant_cfg()
    assert "intraday" in cfg
    intra = cfg["intraday"]
    assert intra["enabled"] is True
    assert intra["mainline_resonance_enabled"] is True
    assert intra["mainline_bonus_return_pct"] == 0.008
    assert intra["non_mainline_penalty_enabled"] is True
    assert intra["live_breadth_enabled"] is True
    assert intra["live_breadth_cache_ttl_seconds"] == 300
    assert intra["intraday_retreat_broken_rate"] == 0.35
    assert intra["card_display_enabled"] is True


def test_intraday_sentinel_ttl_cache():
    mock_pool = {
        "limit_up": 25,
        "limit_down": 2,
        "broken_count": 5,
        "broken_rate": 0.1667,
        "limit_up_stocks": [
            {"code": "600519", "name": "贵州茅台", "industry": "白酒", "consecutive_limit_ups": 2, "change_pct": 10.0},
            {"code": "000858", "name": "五粮液", "industry": "白酒", "consecutive_limit_ups": 2, "change_pct": 10.0},
        ],
        "source": "akshare_mock",
    }

    with patch("agent_reach.daily_run.limit_pool_collector.fetch_akshare_limit_pools", return_value=mock_pool) as mock_fetch:
        res1 = get_live_market_breadth_and_phase()
        assert res1["limit_up"] == 25
        assert res1["source"] == "akshare_mock"
        assert mock_fetch.call_count == 1

        # Second call should hit process cache
        res2 = get_live_market_breadth_and_phase()
        assert res2["limit_up"] == 25
        assert mock_fetch.call_count == 1

        # Force refresh should bypass cache
        res3 = get_live_market_breadth_and_phase(force_refresh=True)
        assert res3["limit_up"] == 25
        assert mock_fetch.call_count == 2


def test_match_symbol_tsp_mainline():
    sample_breadth = {
        "limit_up": 30,
        "broken_rate": 0.15,
        "top_mainlines": [
            {
                "sector": "AI算力",
                "score": 28.5,
                "highest_board": 4,
                "two_board_count": 2,
                "top_stocks": [{"code": "000001", "name": "算力先锋", "change_pct": 10.0}],
            },
            {
                "sector": "机器人",
                "score": 22.0,
                "highest_board": 3,
                "two_board_count": 1,
                "top_stocks": [{"code": "000002", "name": "具身机灵", "change_pct": 10.0}],
            },
            {
                "sector": "光伏设备",
                "score": 14.0,
                "highest_board": 1,
                "two_board_count": 0,
                "top_stocks": [{"code": "000003", "name": "绿能光", "change_pct": 10.0}],
            },
        ],
    }

    # 1. Match code directly in Top 1 mainline
    m1 = match_symbol_tsp_mainline("000001", live_breadth=sample_breadth)
    assert m1.is_mainline is True
    assert m1.sector_name == "AI算力"
    assert m1.score == 28.5
    assert m1.highest_board == 4
    assert m1.rank == 1

    # 2. Match industry keyword in Top 2 mainline
    m2 = match_symbol_tsp_mainline(
        "000999",
        symbol_data={"industry": "具身机器人", "concepts": ["减速器"]},
        live_breadth=sample_breadth,
    )
    assert m2.is_mainline is True
    assert m2.sector_name == "机器人"
    assert m2.rank == 2

    # 3. Match 3rd sector -> not in Top 2
    m3 = match_symbol_tsp_mainline(
        "000003",
        symbol_data={"industry": "光伏设备"},
        live_breadth=sample_breadth,
    )
    assert m3.is_mainline is False
    assert m3.sector_name == "光伏设备"
    assert m3.rank == 3
    assert is_symbol_in_top_n_mainlines("000003", {"industry": "光伏设备"}, top_n=3, live_breadth=sample_breadth) is True
    assert is_symbol_in_top_n_mainlines("000003", {"industry": "光伏设备"}, top_n=2, live_breadth=sample_breadth) is False

    # 4. Symbol in unrelated sector
    m4 = match_symbol_tsp_mainline(
        "600000",
        symbol_data={"industry": "银行"},
        live_breadth=sample_breadth,
    )
    assert m4.is_mainline is False
    assert m4.rank is None
    assert is_symbol_in_top_n_mainlines("600000", {"industry": "银行"}, top_n=3, live_breadth=sample_breadth) is False


def test_intraday_retreat_veto_check():
    # Retreat condition: broken_rate >= 0.35 and limit_down >= 10
    retreat_breadth = {
        "broken_rate": 0.38,
        "limit_down": 12,
        "limit_up": 18,
    }
    is_retreat, msg = check_intraday_retreat_risk(live_breadth=retreat_breadth)
    assert is_retreat is True
    assert "退潮急刹车" in msg
    assert "38.0%" in msg

    # Normal conditions
    normal_breadth = {
        "broken_rate": 0.20,
        "limit_down": 3,
        "limit_up": 35,
    }
    is_normal, _ = check_intraday_retreat_risk(live_breadth=normal_breadth)
    assert is_normal is False


def test_mainline_resonance_bonus_in_decide_trade():
    """Verify Top 2 mainline constituent with score >= 20 receives expected return bonus."""
    settings = {
        "trading": {"friction_min_return_pct": 0.015},
        "tsp_quant": {
            "enabled": True,
            "intraday": {
                "enabled": True,
                "mainline_resonance_enabled": True,
                "mainline_bonus_return_pct": 0.008,
            },
        },
    }

    sample_breadth = {
        "phase": "launching",
        "broken_rate": 0.15,
        "limit_down": 1,
        "limit_up": 28,
        "top_mainlines": [
            {
                "sector": "半导体",
                "score": 26.0,
                "highest_board": 3,
                "top_stocks": [{"code": "688008", "name": "澜起科技"}],
            }
        ],
    }

    class DummyVerdict:
        verdict = "可做"
        mss_final = 75.0
        blocked = False

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.get_live_market_breadth_and_phase",
        return_value=sample_breadth,
    ):
        report = {
            "code": "688008",
            "name": "澜起科技",
            "industry": "半导体",
            "verdict": "可做",
            "mss_final": 75.0,
        }
        snapshot = {
            "code": "688008",
            "name": "澜起科技",
            "industry": "半导体",
            "portfolio": {"cash_ratio": 0.40, "positions": {}},
        }
        # Initial exp_ret is 0.010 (< friction 0.015). With +0.008 bonus, it reaches 0.018 (> 0.015)
        decision = _decide_trade(
            lookback_mss=75.0,
            trend="rising",
            verdict=DummyVerdict(),
            report=report,
            snapshot=snapshot,
            settings=settings,
            trade_index=1,
            expected_return_pct=0.010,
        )

        assert decision.action == "buy"
        assert decision.expected_return_pct == pytest.approx(0.018)
        assert "[TSP主线强共振: 半导体 26.0分]" in decision.reasoning
        assert decision.friction_blocked is False


def test_non_mainline_penalty_in_weak_regime():
    """Verify non-top3 symbols in weak regimes (freezing/repair) suffer threshold penalty (+2.0)."""
    settings = {
        "harness": {"threshold_modes": {"aggressive_entry": "fixed"}},
        "thresholds": {"aggressive_entry": 70.0},
        "tsp_quant": {
            "enabled": True,
            "intraday": {
                "enabled": True,
                "non_mainline_penalty_enabled": True,
            },
        },
    }

    weak_breadth = {
        "phase": "freezing",
        "broken_rate": 0.25,
        "limit_down": 5,
        "limit_up": 8,
        "top_mainlines": [
            {"sector": "银行", "score": 15.0, "highest_board": 1, "top_stocks": []},
            {"sector": "电力", "score": 12.0, "highest_board": 1, "top_stocks": []},
        ],
    }

    class DummyVerdict:
        verdict = "可做"
        mss_final = 71.0
        blocked = False

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.get_live_market_breadth_and_phase",
        return_value=weak_breadth,
    ):
        # Symbol in "纺织" is not in top 3. Baseline aggressive entry is 70.0.
        # Under freezing regime penalty, aggressive becomes 72.0.
        # With lookback_mss 71.0, 71.0 < 72.0 so it cannot buy!
        report = {
            "code": "002000",
            "name": "纺织杂毛",
            "industry": "纺织",
            "verdict": "可做",
            "mss_final": 71.0,
        }
        snapshot = {
            "code": "002000",
            "name": "纺织杂毛",
            "industry": "纺织",
            "portfolio": {"cash_ratio": 0.50, "positions": {}},
        }
        decision = _decide_trade(
            lookback_mss=71.0,
            trend="rising",
            verdict=DummyVerdict(),
            report=report,
            snapshot=snapshot,
            settings=settings,
            trade_index=1,
            expected_return_pct=0.03,
        )

        assert decision.action == "hold"


def test_intraday_retreat_veto_blocks_buy():
    """Verify high broken rate + high limit-down triggers tsp_retreat trade block."""
    settings = {
        "aggressive_entry": 65.0,
        "tsp_quant": {
            "enabled": True,
            "intraday": {
                "enabled": True,
                "intraday_retreat_broken_rate": 0.35,
            },
        },
    }

    retreat_breadth = {
        "phase": "retreat",
        "broken_rate": 0.40,
        "limit_down": 15,
        "limit_up": 12,
        "top_mainlines": [],
    }

    class DummyVerdict:
        verdict = "可做"
        mss_final = 80.0
        blocked = False

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.get_live_market_breadth_and_phase",
        return_value=retreat_breadth,
    ):
        report = {
            "code": "600519",
            "name": "贵州茅台",
            "verdict": "可做",
            "mss_final": 80.0,
        }
        snapshot = {
            "code": "600519",
            "name": "贵州茅台",
            "portfolio": {"cash_ratio": 0.50, "positions": {}},
        }
        decision = _decide_trade(
            lookback_mss=80.0,
            trend="rising",
            verdict=DummyVerdict(),
            report=report,
            snapshot=snapshot,
            settings=settings,
            trade_index=1,
            expected_return_pct=0.03,
        )

        assert decision.action == "hold"
        assert decision.blocked is True
        assert decision.block_kind == "tsp_retreat"
        assert infer_trade_block_kind(decision) == "tsp_retreat"
        msg = format_trade_block_message(decision)
        assert msg == TRADE_BLOCK_MESSAGES["tsp_retreat"]


def test_format_tsp_intraday_card_markdown():
    sample_breadth = {
        "phase_name": "启动期 🚀",
        "broken_rate": 0.182,
        "top_mainlines": [
            {
                "sector": "AI算力",
                "score": 26.5,
                "highest_board": 3,
                "top_stocks": [],
            }
        ],
    }

    symbol_data = {
        "code": "000001",
        "industry": "AI算力",
        "change_pct_3d": 13.5,
    }

    lines = format_tsp_intraday_card_markdown(
        "000001",
        symbol_data=symbol_data,
        settings={"tsp_quant": {"enabled": True}},
        live_breadth=sample_breadth,
    )

    text = "\n".join(lines)
    assert "**TSP 量化哨兵：**" in text
    assert "盘中情绪：启动期 🚀 · 炸板率 18.2%" in text
    assert "主线归属：【AI算力】强度 26.5分 · 身位板 3板" in text
    assert "异动安全垫：" in text
    assert "距交易所 3日" in text


def test_render_intraday_scan_markdown_tsp_integration():
    sample_breadth = {
        "phase_name": "启动期 🚀",
        "broken_rate": 0.12,
        "top_mainlines": [
            {"sector": "工业母机", "score": 24.0, "highest_board": 3, "top_stocks": []}
        ],
    }

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.get_live_market_breadth_and_phase",
        return_value=sample_breadth,
    ):
        scan = {"scan_id": "S3", "mss_final": 65, "verdict": "可做"}
        report = {"code": "000570", "industry": "工业母机", "reasoning": "放量突破"}
        md = render_intraday_scan_markdown(
            scan=scan,
            lookback_mss=63.0,
            lookback_detail=[],
            trend="rising",
            report=report,
            settings={"tsp_quant": {"enabled": True}},
        )

        assert "**TSP 量化哨兵：**" in md
        assert "主线归属：【工业母机】" in md
        assert "盘中情绪：启动期 🚀" in md


def test_intraday_harness_tsp_signals():
    from agent_reach.daily_run.intraday_harness import intraday_to_harness_evidence

    payload_resonance = {
        "scan": {"scan_id": "S4", "code": "688008", "name": "澜起科技"},
        "trade": {
            "action": "buy",
            "decision": {
                "action": "buy",
                "reasoning": "Lookback MSS 75 ≥ 45 且趋势 rising[TSP主线强共振: 半导体 26.0分]",
                "block_kind": None,
            },
        },
    }
    ev1 = intraday_to_harness_evidence(payload_resonance)
    assert any("TSP 主线强共振激励买入：澜起科技" in x for x in ev1["playbook"])

    payload_retreat = {
        "scan": {"scan_id": "S5", "code": "600519", "name": "贵州茅台"},
        "trade": {
            "action": "hold",
            "decision": {
                "action": "hold",
                "reasoning": "TSP 盘中退潮急刹车：炸板率 38.0% 且跌停 12 家，禁止追高买入",
                "block_kind": "tsp_retreat",
            },
        },
    }
    ev2 = intraday_to_harness_evidence(payload_retreat)
    assert any("TSP 盘中退潮急刹车阻断追高：贵州茅台" in x for x in ev2["policy"])

    payload_penalty = {
        "scan": {"scan_id": "S6", "code": "002000", "name": "纺织杂毛"},
        "trade": {
            "action": "hold",
            "decision": {
                "action": "hold",
                "reasoning": "Lookback MSS 71，维持观望[TSP弱势轮动防假突破: 门槛+2.0]",
                "block_kind": None,
            },
        },
    }
    ev3 = intraday_to_harness_evidence(payload_penalty)
    assert any("TSP 弱势轮动提高门槛防假突破：纺织杂毛" in x for x in ev3["playbook"])


def test_midday_cards_and_handoff_tsp_integration():
    from agent_reach.daily_run.midday_cards import build_midday_card_context, render_session_brief_markdown
    from agent_reach.daily_run.midday_handoff import build_midday_handoff

    sample_breadth = {
        "phase": "launching",
        "phase_label": "启动期 🚀",
        "broken_rate": 18.2,
        "limit_up_count": 42,
        "limit_down_count": 2,
        "highest_board": 5,
        "top_mainlines": [
            {"sector": "半导体", "score": 25.0, "highest_board": 4, "rank": 1},
        ],
    }

    scan_result = {
        "scan": {"scan_id": "12:30", "code": "688008", "name": "澜起科技"},
        "lookback_mss": 72.0,
        "state": {"scans": []},
        "enriched": {
            "portfolio": {"holdings": [{"code": "688008", "name": "澜起科技", "price": 60.0}]},
        },
    }

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.get_live_market_breadth_and_phase",
        return_value=sample_breadth,
    ), patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.match_symbol_tsp_mainline",
        return_value=TSPMainlineMatch(True, "半导体", 25.0, 4, 1),
    ):
        ctx = build_midday_card_context(
            scan_result,
            settings={"tsp_quant": {"enabled": True, "midday": {"enabled": True}}},
        )
        assert ctx.tsp_state is not None
        assert ctx.tsp_state["phase"] == "launching"
        assert len(ctx.tsp_lines) > 0

        brief_md = render_session_brief_markdown(ctx)
        assert "TSP 超短微观盘口" in brief_md

        handoff = build_midday_handoff(
            ctx,
            portfolio={"holdings": []},
            enriched={},
        )
        assert "tsp_state" in handoff
        assert handoff["tsp_state"]["phase"] == "launching"


def test_weekly_report_tsp_rollup():
    from datetime import date
    from agent_reach.daily_run.redfox_weekly import summarize_week_market_reviews, render_market_review_weekly_markdown

    mock_reviews = {
        "2026-09-21": {
            "date": "2026-09-21",
            "emotion": {"rating": "亢奋", "broken_rate": 15.0},
            "sector_analysis": {
                "mainline_type": "赛道股",
                "ladder": [{"board": 3, "count": 1}],
                "hot_sectors": [{"name": "半导体", "score": 28.0}],
            },
            "tsp_regime": {"phase": "launching", "phase_label": "启动期 🚀", "session_regime": "supportive"},
        },
        "2026-09-22": {
            "date": "2026-09-22",
            "emotion": {"rating": "亢奋", "broken_rate": 20.0},
            "sector_analysis": {
                "mainline_type": "赛道股",
                "ladder": [{"board": 4, "count": 1}],
                "hot_sectors": [{"name": "半导体", "score": 26.0}],
            },
            "tsp_regime": {"phase": "main_up", "phase_label": "主升期 🔥", "session_regime": "supportive"},
        },
    }

    with patch("agent_reach.daily_run.redfox_weekly.is_trading_day", return_value=(True, "")), \
         patch("agent_reach.daily_run.redfox_weekly.load_market_review", side_effect=lambda d: mock_reviews.get(d)):
        summary = summarize_week_market_reviews(date(2026, 9, 21), date(2026, 9, 22))

    assert "tsp_weekly" in summary
    assert len(summary["tsp_weekly"]["daily_regimes"]) == 2
    assert summary["tsp_weekly"]["max_ladder_height"] == 4

    md = render_market_review_weekly_markdown(summary)
    assert "TSP 超短情绪与主线演化" in md
    assert "启动期" in md
    assert "主升期" in md


def test_forecast_tsp_prior_and_matrix_tagging():
    from agent_reach.daily_run.forecast_operation_matrix import build_master_operation_rows

    structured = {
        "symbols": [
            {
                "code": "688008",
                "name": "澜起科技",
                "confidence_pct": 75.0,
                "change_pct_range_3d": [26.0, 28.5],  # STAR market 3d limit is 30.0%, 28.5 >= 0.85 * 30.0 (25.5)
            }
        ]
    }
    pf = {"holdings": [{"code": "688008", "name": "澜起科技", "shares": 1000, "price": 60.0}], "cash": 50000}

    with patch(
        "agent_reach.daily_run.tsp.intraday_sentinel.is_symbol_in_top_n_mainlines",
        return_value=True,
    ):
        rows = build_master_operation_rows(
            portfolio=pf,
            structured=structured,
            outlook={"operation_plan": []},
            settings={"tsp_quant": {"enabled": True, "forecast": {"enabled": True}}},
        )

    lq_row = next((r for r in rows if "688008" in r["code"]), None)
    assert lq_row is not None
    assert "🌟" in lq_row["name"]  # Mainline resonance tag
    assert "异动监管红线预警" in lq_row["trigger"]  # Deviation lookahead warning
