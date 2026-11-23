# -*- coding: utf-8
"""AR-42: 60s / hot_news failures must not block morning doctor interpretation."""

from unittest.mock import patch

from agent_reach.daily_run.hot_news_collector import HotNewsResult
from agent_reach.daily_run.hot_news_morning_isolation import (
    collect_hot_news_isolated,
    effective_hot_news_base_urls,
    generate_morning_narrative_resilient,
    hot_news_source_from_result,
)


def test_effective_base_urls_skips_local_when_native_down():
    settings = {
        "hot_news": {
            "morning_isolation": {"enabled": True, "skip_local_when_native_down": True},
            "base_urls": ["http://127.0.0.1:8787", "https://60s.viki.moe"],
        }
    }
    with patch(
        "agent_reach.daily_run.hot_news_deploy.native_process_running",
        return_value=False,
    ):
        urls = effective_hot_news_base_urls(
            ["http://127.0.0.1:8787", "https://60s.viki.moe"],
            settings,
            workflow="morning",
        )
    assert urls == ["https://60s.viki.moe"]


@patch("agent_reach.daily_run.hot_news_morning_isolation.collect_hot_news")
def test_collect_hot_news_isolated_marks_degraded_on_empty(mock_collect):
    mock_collect.return_value = HotNewsResult()
    result, meta = collect_hot_news_isolated(
        {"holdings": []},
        settings={"hot_news": {"morning_isolation": {"degraded_on_empty": True}}},
        workflow="morning",
    )
    assert result.items == []
    assert meta["status"] == "degraded"
    src = hot_news_source_from_result(result, meta)
    assert src["status"] == "degraded"
    assert src["severity"] == "warn"


def test_hot_news_source_ok_when_items_present():
    result = HotNewsResult(items=[{"title": "芯片", "platform": "60s"}], summary="ok")
    meta = {"status": "ok"}
    src = hot_news_source_from_result(result, meta)
    assert src["status"] == "ok"
    assert "芯片" in src["summary"] or src["summary"] == "ok"


@patch("agent_reach.daily_run.report_narrative.generate_morning_narrative")
def test_morning_narrative_resilient_fallback(mock_gen):
    mock_gen.side_effect = RuntimeError("llm down")
    snap = {
        "name": "测试",
        "code": "688008",
        "portfolio": {"cash_ratio": 0.5, "holdings": []},
        "sources": {"hot_news": {"status": "degraded", "summary": "60s 降级"}},
    }
    report = {"name": "测试", "verdict": "观察", "mss_final": 52}
    narrative = generate_morning_narrative_resilient(snap, report, settings={})
    assert narrative.get("degraded") is True
    assert narrative.get("skipped") is False
    assert narrative.get("planner") == "deterministic"


@patch("agent_reach.daily_run.macro_collector._fetch_xueqiu_sentiment", return_value=("", [], []))
@patch("agent_reach.daily_run.macro_collector._fetch_xueqiu_hot_stocks", return_value=[])
@patch("agent_reach.daily_run.macro_collector._fetch_index_change", return_value=0.1)
@patch("agent_reach.daily_run.macro_collector._fetch_northbound_flow", return_value=1.0)
@patch("agent_reach.daily_run.hot_news_morning_isolation.collect_hot_news_isolated")
def test_macro_morning_sets_degraded_hot_news_source(
    mock_iso, _nb, _idx, _hot, _xq
):
    from agent_reach.daily_run.macro_collector import collect_macro_context

    mock_iso.return_value = (HotNewsResult(), {"status": "degraded", "severity": "warn"})
    ctx = collect_macro_context({}, settings={}, workflow="morning")
    hot = ctx["sources"]["hot_news"]
    assert hot["status"] == "degraded"
    assert ctx["macro_signals"].get("hot_news_degraded") is True