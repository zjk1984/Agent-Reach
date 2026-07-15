# -*- coding: utf-8
"""Tests for per-symbol daily-run orchestration."""

from unittest.mock import patch

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.snapshot_builder import build_snapshot
from agent_reach.daily_run.symbols import list_target_symbols, resolve_target_symbols
from agent_reach.daily_run.symbol_runner import run_morning_for_symbols
from agent_reach.daily_run.workflows import load_morning_baseline, save_morning_baseline


PORTFOLIO = {
    "primary_code": "688008",
    "holdings": [
        {"code": "688008", "name": "澜起科技", "shares": 100, "cost": 255.87},
        {"code": "002273", "name": "水晶光电", "shares": 300, "cost": 33.81},
    ],
    "watchlist": [
        {"code": "603986", "name": "兆易创新"},
        {"code": "000725", "name": "京东方A"},
    ],
    "mss_breakdown": {"fx": 35, "flow": 48, "global": 38, "sentiment": 50},
}


class TestTargetSymbols:
    def test_list_target_symbols_all(self):
        codes = list_target_symbols(PORTFOLIO, mode="all")
        assert codes == ["688008", "002273", "603986", "000725"]

    def test_resolve_primary_mode(self):
        cfg = load_settings()
        cfg = {**cfg, "schedule": {**(cfg.get("schedule") or {}), "symbols_mode": "primary"}}
        assert resolve_target_symbols(PORTFOLIO, cfg) == ["688008"]

    def test_resolve_all_mode(self):
        cfg = load_settings()
        cfg = {**cfg, "schedule": {**(cfg.get("schedule") or {}), "symbols_mode": "all"}}
        assert len(resolve_target_symbols(PORTFOLIO, cfg)) == 4


class TestPerSymbolSnapshot:
    def test_build_snapshot_uses_symbol_name_for_premarket(self):
        snap = build_snapshot(PORTFOLIO, report_type="premarket", primary_code="002273", enrich=False)
        assert snap["code"] == "002273"
        assert snap["name"] == "002273"


class TestPerSymbolBaselines:
    def test_save_and_load_per_code_baseline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.workflows.morning_baseline_path",
            lambda code: tmp_path / f"{code}.json",
        )
        snap = {"code": "688008", "name": "澜起科技", "price": 100}
        save_morning_baseline(snap, code="688008")
        loaded = load_morning_baseline(code="688008")
        assert loaded["code"] == "688008"


class TestSymbolRunner:
    @patch("agent_reach.daily_run.workflows.run_morning")
    @patch("agent_reach.daily_run.symbol_runner.build_and_save")
    @patch("agent_reach.daily_run.symbol_runner.load_portfolio")
    def test_run_morning_for_symbols(self, mock_pf, mock_build, mock_run, tmp_path):
        mock_pf.return_value = PORTFOLIO
        mock_build.side_effect = [
            ({"code": "688008", "name": "澜起科技"}, tmp_path / "a.json"),
            ({"code": "002273", "name": "水晶光电"}, tmp_path / "b.json"),
        ]
        mock_run.side_effect = [
            {"snapshot": {"code": "688008"}, "feishu": {"ok": 1}},
            {"snapshot": {"code": "002273"}, "feishu": {"ok": 2}},
        ]
        cfg = load_settings()
        cfg = {
            **cfg,
            "schedule": {**(cfg.get("schedule") or {}), "symbols_mode": "holdings"},
        }
        result = run_morning_for_symbols(settings=cfg, push=False, symbols=["688008", "002273"])
        assert len(result["symbol_results"]) == 2
        assert mock_run.call_count == 2
