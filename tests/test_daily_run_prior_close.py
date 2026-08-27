# -*- coding: utf-8
"""Tests for prior close MSS reference in morning reports."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_reach.daily_run.pipeline import build_report, render_markdown
from agent_reach.daily_run.prior_close import (
    attach_prior_close_reference,
    format_prior_close_line,
    load_prior_close_reference,
    prev_trading_day,
    prior_close_date_label,
    save_close_baseline,
)
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.trade_calendar import today_shanghai
from agent_reach.daily_run.verdict import VerdictResult


@pytest.fixture
def settings():
    return load_settings()


class TestPriorCloseReference:
    def test_save_and_load_close_baseline(self, tmp_path, monkeypatch):
        close_dir = tmp_path / "baselines" / "close"
        close_dir.mkdir(parents=True)

        def _path(code: str) -> Path:
            return close_dir / f"{code}.json"

        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.close_baseline_path",
            _path,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.today_shanghai",
            lambda: date(2026, 7, 17),
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.prev_trading_day",
            lambda *args, **kwargs: date(2026, 7, 17),
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.runs_dir",
            lambda: tmp_path / "runs",
        )

        snap = {
            "code": "688008",
            "name": "澜起科技",
            "mss_final": 48.2,
            "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
        }
        verify = {"mss_current": 48.2, "verdict_current": "观察", "name": "澜起科技"}
        save_close_baseline(snapshot=snap, verify=verify)

        loaded = load_prior_close_reference("688008", load_settings())
        assert loaded is not None
        assert loaded["mss_final"] == 48.2
        assert loaded["verdict"] == "观察"

    def test_attach_prior_close_to_premarket_snapshot(self, tmp_path, monkeypatch, settings):
        close_dir = tmp_path / "baselines" / "close"
        close_dir.mkdir(parents=True)
        today = today_shanghai()
        prior = today - timedelta(days=1)
        while prior.weekday() >= 5:
            prior -= timedelta(days=1)

        (close_dir / "688008.json").write_text(
            json.dumps(
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "mss_final": 46.0,
                    "verdict": "观察",
                    "close_date": prior.isoformat(),
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.close_baseline_path",
            lambda code: close_dir / f"{code}.json",
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.prev_trading_day",
            lambda *a, **k: prior,
        )

        snap = attach_prior_close_reference(
            {"code": "688008", "name": "澜起科技", "report_type": "premarket"},
            settings,
        )
        assert snap["prior_close_mss"] == 46.0
        assert snap["prior_close_date"] == prior.isoformat()

    def test_render_markdown_shows_prior_close_delta(self, settings):
        report = build_report(
            {
                "code": "688008",
                "prior_close_mss": 46.0,
                "prior_close_date": "2026-07-16",
                "prior_close_verdict": "观察",
            },
            audit=type("A", (), {"passed": True, "summary": lambda self: "ok", "warnings": []})(),
            verdict=VerdictResult(
                verdict="观察",
                confidence="中",
                mss_final=44.5,
                entry_price=None,
                stop_loss_price=None,
                invalidation="test",
                reasoning="test",
            ),
            settings=settings,
        )
        md = render_markdown(report)
        assert "昨收 MSS" in md
        assert "46.0" in md
        assert "44.5" in md
        assert report["prior_close_delta"] == -1.5

    def test_prev_trading_day_skips_weekend(self):
        friday = date(2026, 7, 17)
        assert prev_trading_day(friday).weekday() < 5

    def test_stale_prior_close_date_label(self):
        label = prior_close_date_label(
            {
                "prior_close_date": "2026-08-18",
                "prior_close_source": "close_baseline_stale",
                "prior_close_stale": True,
            }
        )
        assert label == "2026-08-18·过期"

    def test_intraday_scan_prior_close_fallback(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs" / "2026-08-25"
        runs.mkdir(parents=True)
        close_dir = tmp_path / "baselines" / "close"
        close_dir.mkdir(parents=True)
        (close_dir / "603986.json").write_text(
            json.dumps(
                {
                    "code": "603986",
                    "mss_final": 58.47,
                    "verdict": "观察",
                    "close_date": "2026-08-18",
                }
            ),
            encoding="utf-8",
        )
        manifest = {
            "at": "2026-08-25T10:00:00+00:00",
            "payload": {
                "symbol_results": [
                    {
                        "code": "603986",
                        "result": {
                            "scan": {
                                "scan": {
                                    "scan_id": "S13",
                                    "code": "603986",
                                    "mss_final": 50.4,
                                    "verdict": "观察",
                                    "as_of": "2026-08-25T05:49:58+00:00",
                                }
                            }
                        },
                    }
                ]
            },
        }
        (runs / "intraday_135009.json").write_text(json.dumps(manifest), encoding="utf-8")

        target = date(2026, 8, 25)
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.close_baseline_path",
            lambda code: close_dir / f"{code}.json",
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.prev_trading_day",
            lambda *a, **k: target,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.runs_dir",
            lambda: tmp_path / "runs",
        )

        loaded = load_prior_close_reference("603986", load_settings(), as_of=date(2026, 8, 26))
        assert loaded is not None
        assert loaded["mss_final"] == 50.4
        assert loaded["close_date"] == "2026-08-25"
        assert loaded["source"] == "intraday_scan"
        assert loaded["scan_id"] == "S13"

        line = format_prior_close_line(
            {
                "prior_close_mss": 50.4,
                "prior_close_date": "2026-08-25",
                "prior_close_verdict": "观察",
                "prior_close_source": "intraday_scan",
                "prior_close_scan_id": "S13",
                "mss_final": 49.0,
                "prior_close_delta": -1.4,
            }
        )
        assert "2026-08-25·S13" in line

    def test_file_baseline_wins_over_stale_db(self, tmp_path, monkeypatch):
        close_dir = tmp_path / "baselines" / "close"
        close_dir.mkdir(parents=True)
        target = date(2026, 8, 26)
        (close_dir / "688008.json").write_text(
            json.dumps(
                {
                    "code": "688008",
                    "name": "澜起科技",
                    "mss_final": 48.0,
                    "verdict": "观察",
                    "close_date": "2026-08-26",
                    "_baseline_source": "close_baseline",
                }
            ),
            encoding="utf-8",
        )

        def _fake_db(code, *, settings=None, day=None):
            return {
                "code": code,
                "mss_final": 48.2,
                "verdict": "观察",
                "close_date": "2026-07-17",
                "_baseline_source": "baseline_close_db",
            }

        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.close_baseline_path",
            lambda code: close_dir / f"{code}.json",
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close._read_db_close_baseline",
            lambda norm, *, target_day=None, settings=None: _fake_db(norm, day=target_day),
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.prev_trading_day",
            lambda *a, **k: target,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.runs_dir",
            lambda: tmp_path / "runs",
        )

        loaded = load_prior_close_reference("688008", load_settings(), as_of=date(2026, 8, 27))
        assert loaded is not None
        assert loaded["mss_final"] == 48.0
        assert loaded["source"] == "close_baseline"
        assert loaded.get("scan_id") is None

    def test_intraday_fallback_uses_last_scan_same_shanghai_day(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs" / "2026-08-26"
        runs.mkdir(parents=True)
        target = date(2026, 8, 26)

        def _manifest(scan_id: str, mss: float, as_of: str) -> dict[str, Any]:
            return {
                "at": as_of,
                "payload": {
                    "symbol_results": [
                        {
                            "code": "688008",
                            "result": {
                                "scan": {
                                    "scan": {
                                        "scan_id": scan_id,
                                        "code": "688008",
                                        "mss_final": mss,
                                        "verdict": "观察",
                                        "as_of": as_of,
                                    }
                                }
                            },
                        }
                    ]
                },
            }

        (runs / "intraday_070000.json").write_text(
            json.dumps(_manifest("S1", 51.96, "2026-08-27T07:23:51+08:00")),
            encoding="utf-8",
        )
        (runs / "intraday_150000.json").write_text(
            json.dumps(_manifest("S11", 48.89, "2026-08-26T15:00:50+08:00")),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.close_baseline_path",
            lambda code: tmp_path / "missing" / f"{code}.json",
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close._read_db_close_baseline",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.prev_trading_day",
            lambda *a, **k: target,
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.prior_close.runs_dir",
            lambda: tmp_path / "runs",
        )
        monkeypatch.setattr(
            "agent_reach.daily_run.storage.config.path_under_daily_run_data",
            lambda path: False,
        )

        loaded = load_prior_close_reference("688008", load_settings(), as_of=date(2026, 8, 27))
        assert loaded is not None
        assert loaded["mss_final"] == 48.89
        assert loaded["scan_id"] == "S11"
        assert loaded["source"] == "intraday_scan"
