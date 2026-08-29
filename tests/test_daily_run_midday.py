# -*- coding: utf-8
"""Tests for 12:30 midday refresh workflow."""

from unittest.mock import patch

from agent_reach.daily_run.midday import (
    apply_midday_macro_refresh,
    midday_cfg,
    render_midday_markdown,
    run_midday,
)
from agent_reach.daily_run.schedule import INTRADAY_MAX_SCANS, default_entries


def test_intraday_max_scans_includes_midday():
    assert INTRADAY_MAX_SCANS == 13


def test_default_crontab_has_midday():
    labels = [e.label for e in default_entries()]
    assert any("午盘" in label and "12:30" in label for label in labels)


def test_midday_cfg_enabled_by_default():
    cfg = midday_cfg({"report": {"midday_card_layout": "cards"}, "midday": {"macro_refresh": False}})
    assert cfg["enabled"] is True
    assert cfg["card_layout"] is True
    assert cfg["macro_refresh"] is False
    assert cfg["exclude_from_trend"] is True
    assert cfg["lookback_weight_scale"] == 0.25
    assert cfg["record_scan"] is False


def test_apply_midday_macro_refresh_merges():
    snapshot = {
        "portfolio": {"holdings": [], "watchlist": []},
        "mss_breakdown": {"fx": 40, "flow": 40, "global": 40, "sentiment": 40},
        "sources": {},
    }
    macro = {
        "macro_summary": "北向 +12 亿",
        "macro_signals": {"northbound_flow_yi": 12.0},
        "mss_breakdown": {"flow": 55, "global": 48, "sentiment": 52, "technical": 40, "quant": 40},
        "sources": {"flow": {"summary": "北向净流入 12 亿"}},
    }
    with patch(
        "agent_reach.daily_run.macro_collector.collect_macro_context",
        return_value=macro,
    ), patch(
        "agent_reach.daily_run.macro_collector.enrich_macro_sources",
        side_effect=lambda _pf, sources, _cfg: sources,
    ), patch(
        "agent_reach.daily_run.snapshot_cache.load_daily_cache",
        return_value={},
    ), patch(
        "agent_reach.daily_run.snapshot_cache.save_daily_cache",
    ) as mock_save:
        out = apply_midday_macro_refresh(snapshot, settings={})
    assert out["macro_summary"] == "北向 +12 亿"
    assert out["mss_breakdown"]["flow"] == 55
    mock_save.assert_called_once()


def test_apply_midday_macro_refresh_preserves_session_technical():
    snapshot = {
        "portfolio": {"holdings": [], "watchlist": []},
        "mss_breakdown": {"fx": 40, "flow": 40, "technical": 58, "quant": 57, "risk": 55},
        "sources": {},
    }
    macro = {
        "macro_summary": "宏观 refresh",
        "macro_signals": {},
        "mss_breakdown": {"flow": 44, "global": 46, "sentiment": 46, "technical": 40, "quant": 40},
        "sources": {},
    }
    with patch(
        "agent_reach.daily_run.macro_collector.collect_macro_context",
        return_value=macro,
    ), patch(
        "agent_reach.daily_run.macro_collector.enrich_macro_sources",
        side_effect=lambda _pf, sources, _cfg: sources,
    ), patch(
        "agent_reach.daily_run.snapshot_cache.load_daily_cache",
        return_value={},
    ), patch(
        "agent_reach.daily_run.snapshot_cache.save_daily_cache",
    ):
        out = apply_midday_macro_refresh(snapshot, settings={})
    assert out["mss_breakdown"]["flow"] == 44
    assert out["mss_breakdown"]["technical"] == 58


@patch("agent_reach.daily_run.midday.apply_midday_macro_refresh", side_effect=lambda s, **_: s)
@patch("agent_reach.daily_run.intraday.record_scan_from_evaluation")
@patch("agent_reach.daily_run.pipeline.evaluate_snapshot")
def test_run_midday_records_source_midday_when_record_scan_enabled(mock_eval, mock_record, _mock_macro):
    mock_eval.return_value = {
        "audit": type("A", (), {"passed": True, "warnings": []})(),
        "report": {"verdict": "观察", "mss_final": 44, "reasoning": "午后宜观望"},
        "gate": type("G", (), {"passed": True, "downgraded": False, "missing_fields": []})(),
        "verdict": type("V", (), {"verdict": "观察"})(),
    }
    mock_record.return_value = {
        "scan": {"scan_id": "S10", "mss_final": 44, "verdict": "观察", "source": "midday"},
        "state": {"scans": [{"scan_id": "S10", "source": "midday"}]},
        "lookback_mss": 43.5,
        "lookback_detail": [{"scan_id": "S10", "mss_final": 44, "weight": 1.0, "weighted": 44}],
        "trend": "flat",
        "xueqiu_cross": {},
    }
    result = run_midday(
        {"code": "688008", "name": "澜起", "portfolio": {}},
        settings={"midday": {"enabled": True, "record_scan": True}},
        push=False,
    )
    assert mock_record.call_args.kwargs["source"] == "midday"
    assert "record_scan" in result["steps"]
    assert "早盘验证" in result["markdown"] or "截至 11:30 收盘" in result["markdown"]


@patch("agent_reach.daily_run.midday.apply_midday_macro_refresh", side_effect=lambda s, **_: s)
@patch("agent_reach.daily_run.intraday.record_scan_from_evaluation")
@patch("agent_reach.daily_run.pipeline.evaluate_snapshot")
def test_run_midday_macro_only_skips_record_scan(mock_eval, mock_record, _mock_macro):
    from agent_reach.daily_run.intraday import IntradayState

    state = IntradayState(
        date="2026-08-27",
        scans=[{"scan_id": "S7", "mss_final": 55.0, "verdict": "观察"}],
    )
    with patch("agent_reach.daily_run.intraday.load_state", return_value=state), patch(
        "agent_reach.daily_run.macro_collector.fetch_intraday_xueqiu_cross_alerts",
        return_value={},
    ), patch(
        "agent_reach.daily_run.auditor.run_data_audit",
        return_value=type("A", (), {"passed": True, "warnings": [], "issues": []})(),
    ):
        result = run_midday(
            {"code": "688008", "name": "澜起", "portfolio": {}},
            settings={"midday": {"enabled": True, "record_scan": False}},
            push=False,
        )
    mock_eval.assert_not_called()
    mock_record.assert_not_called()
    assert "macro_only" in result["steps"]
    assert "record_scan" not in result["steps"]
    assert result["scan"]["record_scan_skipped"] is True
    assert "上午盘面" in result["markdown"] or "对持仓影响" in result["markdown"] or "持仓上午速览" in result["markdown"]
    assert len(state.scans) == 1


@patch("agent_reach.daily_run.midday.apply_midday_macro_refresh", side_effect=lambda s, **_: s)
@patch("agent_reach.daily_run.intraday.record_scan_from_evaluation")
@patch("agent_reach.daily_run.midday.evaluate_snapshot")
def test_run_midday_shows_audit_warning_without_blocking(mock_eval, mock_record, _mock_macro):
    """Midday must surface audit failures (like intraday does) instead of pushing silently,
    but unlike morning it must not raise/block the job."""
    mock_eval.return_value = {
        "audit": type("A", (), {"passed": False, "warnings": ["行情覆盖率不足"], "issues": ["quote missing"]})(),
        "report": {"verdict": "观察", "mss_final": 44, "reasoning": "午后宜观望"},
        "gate": type("G", (), {"passed": True, "downgraded": False, "missing_fields": []})(),
        "verdict": type("V", (), {"verdict": "观察"})(),
    }
    mock_record.return_value = {
        "scan": {"scan_id": "S10", "mss_final": 44, "verdict": "观察", "source": "midday"},
        "state": {"scans": [{"scan_id": "S10", "source": "midday"}]},
        "lookback_mss": 43.5,
        "lookback_detail": [{"scan_id": "S10", "mss_final": 44, "weight": 1.0, "weighted": 44}],
        "trend": "flat",
        "xueqiu_cross": {},
    }
    result = run_midday(
        {"code": "688008", "name": "澜起", "portfolio": {}},
        settings={"midday": {"enabled": True, "record_scan": True}},
        push=False,
    )
    assert "数据审计提示" in result["markdown"]
    assert "行情覆盖率不足" in result["markdown"]
    assert "quote missing" in result["markdown"]


def test_render_midday_markdown_sections():
    md = render_midday_markdown(
        {
            "scan": {
                "scan_id": "S8",
                "mss_final": 55.0,
                "verdict": "观察",
                "source": "midday",
                "trend_excluded": True,
            },
            "evaluation": {"report": {"reasoning": "午后观望"}},
            "lookback_mss": 54.0,
            "lookback_detail": [{"scan_id": "S8", "mss_final": 55.0, "weight": 0.25, "weighted": 13.75}],
            "trend": "rising",
            "anchor_trend": "rising",
            "state": {"scans": [{"scan_id": "S8", "source": "midday", "mss_final": 55.0}]},
            "enriched": {"macro_summary": "午休宏观 refresh"},
            "xueqiu_cross": {},
        }
    )
    assert "午盘分析" in md
    assert "上午回顾" in md
    assert "午休宏观刷新" in md
    assert "午后 Lookback" in md
    assert "午休锚点" in md
