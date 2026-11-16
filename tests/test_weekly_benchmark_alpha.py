# -*- coding: utf-8
"""Weekly benchmark alpha visibility — streak + Feishu banner fields."""

from datetime import date
from unittest.mock import patch

from agent_reach.daily_run.quant_digest import quant_digest_feishu_card
from agent_reach.daily_run.weekly_card_metrics import (
    build_benchmark_alpha_visibility,
    compute_weekly_benchmark_underperform_streak,
    enrich_weekly_metrics_benchmark_alpha,
    render_benchmark_alpha_banner,
)
from agent_reach.daily_run.weekly_signals import (
    build_performance_overview_table,
    render_performance_overview_markdown,
)


def _weekly_metrics(port: float, bench: float) -> dict:
    excess = round(port - bench, 2)
    return {
        "absolute_return_pct": port,
        "excess_return_pct": excess,
        "benchmark": {"ok": True, "name": "沪深300", "return_pct": bench},
    }


class TestBenchmarkUnderperformStreak:
    def test_streak_counts_trailing_underperform_weeks(self):
        with patch(
            "agent_reach.daily_run.weekly_signals.portfolio_return_between",
            side_effect=[0.5, 0.2, 1.0],
        ), patch(
            "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
            side_effect=[
                {"ok": True, "return_pct": 0.7},
                {"ok": True, "return_pct": 0.3},
                {"ok": True, "return_pct": 0.0},
            ],
        ):
            info = compute_weekly_benchmark_underperform_streak(
                date(2026, 8, 8),
                current_week_excess=-0.5,
            )
        assert info["underperform_week_streak"] == 3

    def test_streak_breaks_on_outperform_week(self):
        with patch(
            "agent_reach.daily_run.weekly_signals.portfolio_return_between",
            return_value=2.0,
        ), patch(
            "agent_reach.daily_run.weekly_card_metrics.fetch_benchmark_weekly_return",
            return_value={"ok": True, "return_pct": 1.0},
        ):
            info = compute_weekly_benchmark_underperform_streak(
                date(2026, 8, 8),
                current_week_excess=0.5,
            )
        assert info["underperform_week_streak"] == 0

    def test_verdict_when_streak_ge_2(self):
        with patch(
            "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
            return_value={"underperform_week_streak": 2, "weeks": []},
        ):
            alpha = build_benchmark_alpha_visibility(
                _weekly_metrics(0.5, 1.2),
                week_start=date(2026, 8, 4),
                week_end=date(2026, 8, 8),
            )
        assert alpha["underperform_week_streak"] == 2
        assert alpha["verdict"] and "已连续" in alpha["verdict"]


class TestBenchmarkAlphaBanner:
    def test_banner_fields_on_card(self):
        with patch(
            "agent_reach.daily_run.weekly_card_metrics.compute_weekly_benchmark_underperform_streak",
            return_value={"underperform_week_streak": 0, "weeks": []},
        ):
            metrics = enrich_weekly_metrics_benchmark_alpha(
                _weekly_metrics(2.0, 1.5),
                week_start=date(2026, 8, 4),
                week_end=date(2026, 8, 8),
            )
        md = "\n".join(render_benchmark_alpha_banner(metrics))
        assert "相对基准（首屏）" in md
        assert "组合周收益" in md
        assert "超额" in md
        assert "+0.50%" in md

    def test_performance_overview_includes_banner(self):
        table = build_performance_overview_table(
            week_start=date(2026, 8, 4),
            week_end=date(2026, 8, 8),
            start_total=100000,
            end_total=101500,
            weekly_metrics=_weekly_metrics(1.5, 0.8),
        )
        assert table.get("benchmark_alpha")
        md = "\n".join(render_performance_overview_markdown(table))
        assert "相对基准（首屏）" in md
        assert "收益总览" in md

    def test_quant_digest_feishu_shows_alpha(self):
        payload = {
            "week_start": "2026-08-04",
            "week_end": "2026-08-08",
            "pnl": {
                "weekly_pnl": 1500,
                "weekly_pnl_pct": 1.5,
                "benchmark_alpha": {
                    "fund_return_pct": 1.5,
                    "benchmark_return_pct": 0.8,
                    "excess_return_pct": 0.7,
                    "underperform_week_streak": 2,
                    "verdict": "已连续 2 周跑输沪深300",
                },
            },
            "trades": {"trade_count": 0, "realized_pnl": 0},
            "job_health": {"jobs": []},
            "recent_coverage": [],
            "playbook_delta": {},
        }
        _title, body, _tpl = quant_digest_feishu_card(payload)
        assert "vs 基准" in body
        assert "超额 +0.70%" in body
        assert "连续跑输基准" in body