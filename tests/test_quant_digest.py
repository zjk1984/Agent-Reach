# -*- coding: utf-8
"""Tests for quant PM weekly digest pure builders."""

from datetime import date

from agent_reach.daily_run.daily_pnl_history import DailyPnlRecord
from agent_reach.daily_run.quant_digest import (
    build_quant_digest_payload,
    last_n_trading_days,
    manifest_jobs_by_day,
    playbook_delta_from_refinements,
    playbook_entries_touched_in_week,
    render_quant_digest_markdown,
    summarize_job_health_snapshot,
    summarize_pnl_rows,
    summarize_recent_job_coverage,
    summarize_trades,
    quant_digest_feishu_card,
)


class TestLastNTradingDays:
    def test_friday_end_returns_five_weekdays(self):
        fri = date(2026, 7, 10)
        days = last_n_trading_days(fri, 5, settings={})
        assert len(days) == 5
        assert days[-1] == fri
        assert days[0] == date(2026, 7, 6)


class TestSummarizePnlRows:
    def test_weekly_sum_and_daily_table(self):
        rows = [
            DailyPnlRecord(date="2026-07-06", daily_pnl=100.0, daily_pnl_pct=0.1, end_total=10100.0),
            DailyPnlRecord(date="2026-07-07", daily_pnl=-50.0, daily_pnl_pct=-0.05, end_total=10050.0),
            DailyPnlRecord(date="2026-07-08", daily_pnl=200.0, daily_pnl_pct=0.2, end_total=10250.0),
        ]
        out = summarize_pnl_rows(
            rows,
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 10),
        )
        assert out["weekly_pnl"] == 250.0
        assert out["trading_days_with_pnl"] == 3
        assert out["end_total"] == 10250.0
        md = render_quant_digest_markdown(
            build_quant_digest_payload(
                as_of=date(2026, 7, 11),
                pnl_rows=rows,
                trades=[],
                job_health={"jobs": {}},
                manifests=[],
                refinements=[],
                playbook_entries={},
            )
        )
        assert "250.00" in md
        assert "2026-07-06" in md


class TestSummarizeTrades:
    def test_counts_and_realized(self):
        trades = [
            {
                "date": "2026-07-07",
                "actions": [
                    {"side": "buy", "code": "688008", "name": "澜起", "shares": 100, "amount": 10000, "commission": 15},
                ],
            },
            {
                "date": "2026-07-08",
                "actions": [
                    {"side": "sell", "code": "688008", "name": "澜起", "shares": 100, "amount": 10500, "commission": 16},
                ],
            },
        ]
        out = summarize_trades(trades)
        assert out["trade_count"] == 2
        assert out["buys"] == 1
        assert out["sells"] == 1
        assert out["realized_pnl"] == 469.0


class TestJobHealthAndCoverage:
    def test_snapshot_and_manifest_gaps(self):
        health = {
            "jobs": {
                "close": {"consecutive_failures": 0, "last_success_at": "2026-07-10T10:00:00Z"},
                "morning": {"consecutive_failures": 2, "last_error": "timeout"},
            }
        }
        rows = summarize_job_health_snapshot(health)
        assert len(rows) == 2
        by_day = manifest_jobs_by_day(
            [
                {"_run_date": "2026-07-09", "job": "morning"},
                {"_run_date": "2026-07-09", "job": "midday"},
                {"_run_date": "2026-07-09", "job": "intraday"},
                {"_run_date": "2026-07-09", "job": "close"},
                {"_run_date": "2026-07-10", "job": "morning"},
            ]
        )
        cov = summarize_recent_job_coverage(
            [date(2026, 7, 9), date(2026, 7, 10)],
            by_day,
        )
        assert cov[0]["ok"] is True
        assert cov[1]["ok"] is False
        assert "close" in cov[1]["missing"]


class TestPlaybookDelta:
    def test_refinements_and_entries(self):
        refs = [
            {
                "id": "refine_0001",
                "job": "close",
                "trigger": "harness",
                "created_at": "2026-07-08T12:00:00Z",
                "changes": ["update playbook/foo"],
                "edits": [{"kind": "playbook", "action": "update", "entry_id": "foo"}],
            },
            {
                "id": "refine_old",
                "job": "morning",
                "trigger": "x",
                "created_at": "2026-06-01T12:00:00Z",
                "changes": ["playbook old"],
                "edits": [],
            },
        ]
        delta = playbook_delta_from_refinements(
            refs,
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 10),
        )
        assert len(delta) == 1
        assert delta[0]["id"] == "refine_0001"

        touched = playbook_entries_touched_in_week(
            {
                "a": {"id": "a", "title": "T1", "updated_at": "2026-07-07T00:00:00Z"},
                "b": {"id": "b", "title": "T2", "updated_at": "2026-05-01T00:00:00Z"},
            },
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 10),
        )
        assert len(touched) == 1
        assert touched[0]["title"] == "T1"


class TestFeishuCard:
    def test_template_from_sign(self):
        payload = build_quant_digest_payload(
            as_of=date(2026, 7, 11),
            pnl_rows=[DailyPnlRecord(date="2026-07-10", daily_pnl=-10.0)],
            trades=[],
            job_health={"jobs": {}},
            manifests=[],
            refinements=[],
            playbook_entries={},
        )
        title, body, tpl = quant_digest_feishu_card(payload)
        assert "digest" in title
        assert tpl == "red"
        assert "-10.00" in body
