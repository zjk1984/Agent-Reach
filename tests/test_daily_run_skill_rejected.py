# -*- coding: utf-8
"""Tests for rejected strategy guardrails."""

from datetime import date

from agent_reach.daily_run.skill_improvements_apply import _normalize_report_for_writeback
from agent_reach.daily_run.skill_rejected import (
    add_rejected_strategy,
    filter_rejected_items,
    is_rejected_title,
    load_active_rejected_records,
    refresh_rejected_strategies_for_week,
    trade_blocked_by_rejected,
)


class TestSkillRejected:
    def test_filter_rejected_items(self, tmp_path, monkeypatch):
        path = tmp_path / "rejected_strategies.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._REJECTED_PATH", path)
        settings = {"rejected_strategies": {"active_week_only": False}}
        add_rejected_strategy(
            "加大 base_spread",
            "曾导致 MSS 过宽",
            week_start="2026-08-10",
            week_end="2026-08-14",
            settings=settings,
        )
        assert is_rejected_title("加大 base_spread", settings=settings)
        kept, blocked = filter_rejected_items(
            [{"title": "加大 base_spread", "detail": "retry"}, {"title": "新策略", "detail": "ok"}],
            settings=settings,
        )
        assert len(kept) == 1
        assert kept[0]["title"] == "新策略"
        assert blocked == ["加大 base_spread"]

    def test_normalize_report_filters_rejected(self, tmp_path, monkeypatch):
        path = tmp_path / "rejected_strategies.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._REJECTED_PATH", path)
        settings = {"rejected_strategies": {"active_week_only": False}}
        add_rejected_strategy("bad idea", "failed backtest", settings=settings)
        out = _normalize_report_for_writeback(
            {
                "process_improvements": [{"title": "bad idea", "detail": "x"}],
                "skill_learning": [],
            }
        )
        assert out["process_improvements"] == []
        assert "bad idea" in (out.get("_rejected_blocked") or [])

    def test_active_week_only_filters_by_week(self, tmp_path, monkeypatch):
        path = tmp_path / "rejected_strategies.jsonl"
        archive = tmp_path / "rejected_strategies_archive.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._REJECTED_PATH", path)
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._ARCHIVE_PATH", archive)
        settings = {"rejected_strategies": {"active_week_only": True}}
        add_rejected_strategy(
            "禁止接飞刀追涨",
            "旧周已证伪",
            week_start="2026-08-03",
            week_end="2026-08-07",
            settings=settings,
        )
        from agent_reach.daily_run.weekly_report import trading_week_range

        as_of = date(2026, 8, 12)
        monday, friday = trading_week_range(as_of)
        add_rejected_strategy(
            "禁止接飞刀追涨",
            "当周有效",
            week_start=monday.isoformat(),
            week_end=friday.isoformat(),
            settings=settings,
        )
        active = load_active_rejected_records(as_of=as_of, settings=settings)
        assert len(active) == 1
        assert active[0]["reason"] == "当周有效"
        monkeypatch.setattr("agent_reach.daily_run.trade_calendar.today_shanghai", lambda: as_of)
        blocked = trade_blocked_by_rejected(
            "buy",
            name="中际旭创",
            settings={**settings, "harness": {}},
        )
        assert blocked

    def test_refresh_archives_and_adds_next_week(self, tmp_path, monkeypatch):
        path = tmp_path / "rejected_strategies.jsonl"
        archive = tmp_path / "rejected_strategies_archive.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._REJECTED_PATH", path)
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._ARCHIVE_PATH", archive)
        settings = {
            "rejected_strategies": {
                "weekly_refresh": True,
                "active_week_only": True,
                "archive_expired": True,
                "auto_add_from_weekly": True,
            }
        }
        add_rejected_strategy(
            "旧策略",
            "应归档",
            week_start="2026-08-03",
            week_end="2026-08-07",
            settings=settings,
        )
        report = {
            "week_start": "2026-08-10",
            "week_end": "2026-08-14",
            "weekly_pnl_pct": -1.5,
            "macro_signals": {"verdict": "回避"},
            "buy_rules_whatif": {"skipped": True},
        }
        result = refresh_rejected_strategies_for_week(report, settings)
        assert result.get("skipped") is False
        assert result["archived"] == 1
        assert result["added"] == ["禁止接飞刀追涨"]
        assert archive.exists()
        active = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(active) == 1
        row = __import__("json").loads(active[0])
        assert row["title"] == "禁止接飞刀追涨"
        assert row["week_start"] == result["target_week_start"]

    def test_add_rejected_dedupes_same_week(self, tmp_path, monkeypatch):
        path = tmp_path / "rejected_strategies.jsonl"
        monkeypatch.setattr("agent_reach.daily_run.skill_rejected._REJECTED_PATH", path)
        settings = {"rejected_strategies": {"active_week_only": False}}
        first = add_rejected_strategy("dup", "one", week_start="2026-08-10", week_end="2026-08-14", settings=settings)
        second = add_rejected_strategy("dup", "two", week_start="2026-08-10", week_end="2026-08-14", settings=settings)
        assert first["id"] == second["id"]
        assert path.read_text(encoding="utf-8").count("\n") == 1
