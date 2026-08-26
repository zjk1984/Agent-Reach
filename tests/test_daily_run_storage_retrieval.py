# -*- coding: utf-8
"""Tests for storage retrieval injected into LLM prompts."""

from __future__ import annotations

import pytest

from agent_reach.daily_run.storage import reset_store
from agent_reach.daily_run.storage.distill import run_distill
from agent_reach.daily_run.storage.hooks import on_trade_ledger
from agent_reach.daily_run.storage.retrieval import (
    attach_storage_retrieval,
    build_storage_retrieval_context,
    extract_symbol_codes,
)


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    db_path = tmp_path / "daily_run.db"
    settings = {
        "storage": {
            "enabled": True,
            "backend": "sqlite",
            "sqlite_path": str(db_path),
            "distill": {"enabled": True, "auto_after_close": False},
            "retrieval": {"enabled": True},
        }
    }
    monkeypatch.setenv("AGENT_REACH_STORAGE", "1")
    monkeypatch.setattr(
        "agent_reach.daily_run.settings.load_settings",
        lambda path=None: settings,
    )
    reset_store()
    yield {"db_path": db_path, "settings": settings}
    reset_store()


def test_extract_symbol_codes_from_snapshot():
    snapshot = {
        "code": "603986",
        "portfolio": {
            "holdings": [{"code": "688008"}],
            "watchlist": [{"code": "002273"}],
        },
    }
    assert extract_symbol_codes(snapshot) == ["603986", "688008", "002273"]


def test_retrieval_disabled_when_storage_off():
    block = build_storage_retrieval_context(
        settings={"storage": {"enabled": False}},
        codes=["603986"],
        job="morning",
    )
    assert block == {}


def test_retrieval_returns_atoms_and_trades(storage_env):
    settings = storage_env["settings"]
    on_trade_ledger(
        {
            "at": "2026-08-25T08:00:00+00:00",
            "trade_id": "T1",
            "decision_action": "buy",
            "actions": [
                {
                    "side": "buy",
                    "code": "603986",
                    "name": "兆易创新",
                    "shares": 100,
                    "price": 120.5,
                    "amount": 12050.0,
                    "commission": 18.0,
                    "reasoning": "test buy",
                }
            ],
        }
    )
    run_distill(settings=settings, limit=20)
    block = build_storage_retrieval_context(
        settings=settings,
        codes=["603986"],
        job="morning",
    )
    assert block.get("codes") == ["603986"]
    assert block.get("atoms")
    assert block.get("trades")
    assert any("603986" in str(row.get("line") or "") for row in block["trades"])


def test_attach_storage_retrieval_adds_block(storage_env):
    settings = storage_env["settings"]
    on_trade_ledger(
        {
            "at": "2026-08-25T09:00:00+00:00",
            "trade_id": "T2",
            "decision_action": "sell",
            "actions": [
                {
                    "side": "sell",
                    "code": "603986",
                    "name": "兆易创新",
                    "shares": 50,
                    "price": 125.0,
                    "amount": 6250.0,
                    "commission": 9.0,
                    "reasoning": "trim",
                }
            ],
        }
    )
    run_distill(settings=settings, limit=20)
    payload = attach_storage_retrieval(
        {"job": "morning", "code": "603986", "name": "兆易创新"},
        settings=settings,
        job="morning",
    )
    assert "storage_retrieval" in payload
    assert payload["storage_retrieval"]["trades"]


def test_retrieval_respects_job_disable_flag(storage_env):
    settings = dict(storage_env["settings"])
    settings["storage"] = dict(settings["storage"])
    settings["storage"]["retrieval"] = {
        "enabled": True,
        "llm_jobs": {"morning": False},
    }
    block = build_storage_retrieval_context(settings=settings, codes=["603986"], job="morning")
    assert block == {}
