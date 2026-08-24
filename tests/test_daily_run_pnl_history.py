# -*- coding: utf-8
"""Tests for daily P&L history and charts."""

import json
from datetime import date
from pathlib import Path

from agent_reach.daily_run.daily_pnl_history import (
    append_daily_pnl,
    attach_cumulative_pnl,
    backfill_from_manifests,
    detect_pnl_history_gaps,
    load_daily_pnl_history,
    render_pnl_history_markdown,
    render_pnl_line_chart_ascii,
    render_pnl_line_chart_svg,
    summary_to_history_row,
)


def _summary(day: str, pnl: float, *, start: float = 100000, end: float | None = None) -> dict:
    end_total = end if end is not None else start + pnl
    return {
        "as_of": day,
        "start_total": start,
        "end_total": end_total,
        "daily_pnl": pnl,
        "daily_pnl_pct": round(pnl / start * 100, 2),
        "realized_pnl": 0.0,
        "capital_net_flow": 0.0,
    }


class TestDailyPnlHistory:
    def test_summary_to_history_row(self):
        row = summary_to_history_row(_summary("2026-08-15", 500.0))
        assert row is not None
        assert row.date == "2026-08-15"
        assert row.daily_pnl == 500.0

    def test_append_upserts_by_date(self, tmp_path: Path):
        path = tmp_path / "pnl_history.jsonl"
        append_daily_pnl(_summary("2026-08-15", 500.0), path=path)
        append_daily_pnl(_summary("2026-08-16", -200.0), path=path)
        append_daily_pnl(_summary("2026-08-15", 800.0), path=path)

        rows = load_daily_pnl_history(path=path)
        assert len(rows) == 2
        assert rows[0].daily_pnl == 800.0
        assert rows[1].daily_pnl == -200.0

    def test_cumulative_pnl(self, tmp_path: Path):
        path = tmp_path / "pnl_history.jsonl"
        append_daily_pnl(_summary("2026-08-15", 500.0), path=path)
        append_daily_pnl(_summary("2026-08-16", -200.0), path=path)
        rows = load_daily_pnl_history(path=path)
        assert rows[-1].cumulative_pnl == 300.0

    def test_backfill_from_manifests(self, tmp_path: Path, monkeypatch):
        runs = tmp_path / "runs"
        day_dir = runs / "2026-08-17"
        day_dir.mkdir(parents=True)
        manifest = {
            "job": "close",
            "payload": {
                "result": {
                    "portfolio_summary": _summary("2026-08-17", -575.0, start=91938, end=91363),
                }
            },
        }
        (day_dir / "close_153000.json").write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )

        hist_path = tmp_path / "pnl_history.jsonl"
        monkeypatch.setattr(
            "agent_reach.daily_run.weekly_report.runs_dir",
            lambda: runs,
        )
        result = backfill_from_manifests(
            start=date(2026, 8, 17),
            end=date(2026, 8, 17),
            path=hist_path,
        )
        assert result["imported"] == 1
        rows = load_daily_pnl_history(path=hist_path)
        assert len(rows) == 1
        assert rows[0].daily_pnl == -575.0

    def test_ascii_chart_contains_points(self, tmp_path: Path):
        rows = attach_cumulative_pnl(
            [
                summary_to_history_row(_summary("2026-08-15", 500.0)),
                summary_to_history_row(_summary("2026-08-16", -200.0)),
            ]
        )
        chart = render_pnl_line_chart_ascii(rows, value_key="daily_pnl")
        assert "●" in chart
        assert "08-15" in chart or "8-15" in chart

    def test_svg_chart(self):
        rows = attach_cumulative_pnl(
            [
                summary_to_history_row(_summary("2026-08-15", 500.0)),
                summary_to_history_row(_summary("2026-08-16", -200.0)),
            ]
        )
        svg = render_pnl_line_chart_svg(rows, value_key="cumulative_pnl")
        assert "<polyline" in svg
        assert "2026-08-16" in svg

    def test_markdown_clarifies_cumulative_is_nav_based(self):
        """M2: the 累计 column should be labeled distinctly from the close
        card's 总收益 (FIFO) so the two unrelated 'cumulative' figures aren't
        mistaken for the same number."""
        rows = attach_cumulative_pnl([summary_to_history_row(_summary("2026-08-15", 500.0))])
        md = render_pnl_history_markdown(rows)
        assert "净值口径" in md
        assert "总收益" in md


class TestDetectPnlHistoryGaps:
    def test_no_gaps_when_all_trading_days_recorded(self, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
            lambda: {"2026-08-17", "2026-08-18", "2026-08-19"},
        )
        rows = [
            summary_to_history_row(_summary("2026-08-17", 100.0)),
            summary_to_history_row(_summary("2026-08-18", 100.0)),
            summary_to_history_row(_summary("2026-08-19", 100.0)),
        ]
        gaps = detect_pnl_history_gaps(
            rows, start=date(2026, 8, 17), end=date(2026, 8, 19)
        )
        assert gaps == []

    def test_flags_missing_trading_day(self, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
            lambda: {"2026-08-17", "2026-08-18", "2026-08-19"},
        )
        rows = [
            summary_to_history_row(_summary("2026-08-17", 100.0)),
            # 2026-08-18 missing (e.g. cron crashed) -> should be flagged.
            summary_to_history_row(_summary("2026-08-19", 100.0)),
        ]
        gaps = detect_pnl_history_gaps(
            rows, start=date(2026, 8, 17), end=date(2026, 8, 19)
        )
        assert gaps == ["2026-08-18"]

    def test_non_trading_days_are_not_gaps(self, monkeypatch):
        """A weekend with no trade-date-calendar coverage falls back to the
        weekday heuristic and should never be reported as a gap."""
        monkeypatch.setattr(
            "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
            lambda: set(),
        )
        # 2026-08-15 and 2026-08-16 are a Sat/Sun.
        rows: list = []
        gaps = detect_pnl_history_gaps(
            rows, start=date(2026, 8, 15), end=date(2026, 8, 16)
        )
        assert gaps == []
