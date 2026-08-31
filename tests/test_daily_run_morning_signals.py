# -*- coding: utf-8
"""Tests for morning card signals (action checklist, risks, prediction verify)."""

from agent_reach.daily_run.morning_cards import (
    MorningCardContext,
    MorningSymbolRow,
    render_action_checklist_markdown,
    render_holdings_overview_markdown,
    render_morning_card_sections,
    render_today_risk_markdown,
)
from agent_reach.daily_run.morning_signals import (
    build_action_checklist_rows,
    build_yesterday_prediction_lines,
    collect_time_nodes,
    render_holdings_snapshot_table_markdown,
    render_time_nodes_markdown,
)

PORTFOLIO = {
    "total": 100000.0,
    "cash": 40000.0,
    "holdings": [
        {
            "code": "300308",
            "name": "中际旭创",
            "shares": 100,
            "price": 123.5,
            "open": 123.5,
            "prev_close": 125.3,
            "change_pct": -1.44,
            "volume_ratio": 0.8,
            "sector": "通信",
        },
        {
            "code": "000725",
            "name": "京东方",
            "shares": 500,
            "price": 4.2,
            "open": 4.18,
            "prev_close": 4.22,
            "change_pct": -0.8,
            "volume_ratio": 0.9,
            "sector": "面板",
        },
        {
            "code": "002273",
            "name": "水晶光电",
            "shares": 300,
            "price": 34.0,
            "open": 34.2,
            "prev_close": 33.8,
            "change_pct": 0.6,
            "volume_ratio": 1.2,
            "sector": "光学",
        },
    ],
}


def _ctx(**kwargs) -> MorningCardContext:
    defaults = {
        "portfolio": PORTFOLIO,
        "symbol_rows": [
            MorningSymbolRow(
                code="300308",
                name="中际旭创",
                holding=PORTFOLIO["holdings"][0],
                report={
                    "verdict": "观察",
                    "mss_final": 62.0,
                    "stop_loss_price": 120.0,
                    "entry_price": 130.0,
                    "reasoning": "冲高回落",
                },
                snapshot={"volume_ratio": 0.8},
            ),
            MorningSymbolRow(
                code="000725",
                name="京东方",
                holding=PORTFOLIO["holdings"][1],
                report={"verdict": "观察", "mss_final": 55.0, "reasoning": "企稳"},
                snapshot={},
            ),
            MorningSymbolRow(
                code="002273",
                name="水晶光电",
                holding=PORTFOLIO["holdings"][2],
                report={"verdict": "可做", "mss_final": 58.0, "entry_price": 35.0},
                snapshot={},
            ),
        ],
        "macro_signals": {
            "index_change_pct": -0.3,
            "northbound_flow_yi": -5.0,
            "hot_topics": [{"title": "制造业PMI低于预期"}],
        },
        "primary_snapshot": {"sources": {}, "macro_signals": {"hot_topics": []}},
        "global_markets": {
            "as_of_label": "截至 08:00",
            "ok_count": 1,
            "required_count": 1,
            "indices": [],
        },
    }
    defaults.update(kwargs)
    return MorningCardContext(**defaults)


class TestMorningSignals:
    def test_action_checklist_table(self):
        rows = build_action_checklist_rows(_ctx())
        assert len(rows) == 3
        md = render_action_checklist_markdown(_ctx())
        assert "**今日操作清单**" in md
        assert "| 股票 | 操作 | 触发条件 | 目标仓位 |" in md
        assert "中际旭创" in md
        by_name = {row["name"]: row for row in rows}
        assert by_name["中际旭创"]["trigger"] != "—"
        assert "120" in by_name["中际旭创"]["trigger"] or "130" in by_name["中际旭创"]["trigger"]
        assert "**今日时间节点**" in md
        assert "09:30" in md
        assert "定方向" in md

    def test_action_checklist_uses_close_handoff_trigger(self):
        ctx = _ctx(
            close_handoff={
                "tomorrow_focus": [
                    {
                        "code": "688008",
                        "name": "澜起科技",
                        "text": "触发做多：在 210 元附近缩量企稳",
                    }
                ]
            },
            symbol_rows=[
                MorningSymbolRow(
                    code="688008",
                    name="澜起科技",
                    holding={
                        "code": "688008",
                        "name": "澜起科技",
                        "shares": 100,
                        "price": 205.0,
                    },
                    report={"verdict": "观察", "mss_final": 50.0},
                    snapshot={},
                )
            ],
            portfolio={
                "total": 100000.0,
                "cash": 80000.0,
                "holdings": [
                    {
                        "code": "688008",
                        "name": "澜起科技",
                        "shares": 100,
                        "price": 205.0,
                    }
                ],
            },
        )
        rows = build_action_checklist_rows(ctx)
        assert rows[0]["trigger"] == "触发做多：在 210 元附近缩量企稳"

    def test_holdings_snapshot_table_format(self):
        md = render_holdings_snapshot_table_markdown(_ctx())
        assert "| 股票 | 昨收 | 今开 | 涨跌幅 | 成交量比 | MSS | 标签 |" in md
        assert "125.30" in md
        assert "123.50" in md
        assert "-1.44%" in md
        assert "0.8x" in md
        assert "观望" in md

    def test_overview_includes_prediction_validation(self, monkeypatch):
        from agent_reach.daily_run import morning_signals as signals

        monkeypatch.setattr(
            signals,
            "build_yesterday_prediction_lines",
            lambda *_a, **_k: [
                "- 昨日预测「中际旭创 冲高回落」→ ✅ 实际低开 1.4%，当前 -1.4%",
            ],
        )
        md = render_holdings_overview_markdown(_ctx())
        assert "**昨日预测验证**" in md
        assert "中际旭创" in md
        assert "**持仓早盘速览**" in md

    def test_today_risk_sections(self):
        ctx = _ctx(
            symbol_rows=[
                MorningSymbolRow(
                    code="300308",
                    name="中际旭创",
                    holding=PORTFOLIO["holdings"][0],
                    report={
                        "verdict": "回避",
                        "mss_final": 32.0,
                        "invalidation": "财报披露窗口",
                    },
                    snapshot={},
                )
            ],
            macro_signals={
                "index_change_pct": -1.5,
                "northbound_flow_yi": -25.0,
                "hot_topics": [{"title": "监管整顿光学行业"}],
            },
        )
        md = render_today_risk_markdown(ctx)
        assert "**⚠️ 今日风险**" in md
        assert "**持仓风险**" in md
        assert "财报" in md

    def test_card_order_starts_with_action_and_overview(self):
        sections = render_morning_card_sections(_ctx())
        categories = [s.category for s in sections]
        assert categories[0] == "action_checklist"
        assert categories[1] == "holdings_overview"
        assert "today_risk" in categories

    def test_collect_time_nodes_from_macro(self):
        nodes = collect_time_nodes(_ctx())
        assert any(row["time"] == "09:30" for row in nodes)
        assert any("制造业" in row["event"] or "PMI" in row["event"] for row in nodes)

    def test_render_time_nodes_markdown(self):
        md = render_time_nodes_markdown(
            [{"time": "10:00", "event": "制造业PMI公布", "impact": "大盘波动"}]
        )
        assert "| 时间 | 事件 | 影响 |" in md
        assert "10:00" in md

    def test_prediction_lines_empty_without_baseline(self, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.load_close_baseline",
            lambda *_a, **_k: None,
        )
        assert build_yesterday_prediction_lines(_ctx()) == []
