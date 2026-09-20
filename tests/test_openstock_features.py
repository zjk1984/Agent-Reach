# -*- coding: utf-8
"""OpenStock-inspired features: alerts, alignment, LLM fallback, profile, checkpoint."""

import json

import pytest

from agent_reach.daily_run.job_checkpoint import (
    clear_checkpoint,
    is_step_done,
    load_checkpoint,
    mark_step_done,
)
from agent_reach.daily_run.price_alerts import (
    PriceAlert,
    _condition_met,
    active_alerts,
    add_alert,
    load_alerts,
    remove_alert,
    save_alerts,
)
from agent_reach.daily_run.sentiment_alignment import (
    build_symbol_sentiment_alignment,
    get_source_alignment,
    render_sentiment_alignment_markdown,
)
from agent_reach.daily_run.user_profile import (
    load_user_profile,
    profile_sector_match,
    save_user_profile,
    watchlist_profile_score_adjustment,
)


def test_price_alert_add_remove(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_reach.daily_run.price_alerts.alerts_path", lambda: tmp_path / "alerts.json")
    alert = add_alert(code="000725", target_price=5.8, condition="ABOVE", name="京东方A")
    assert alert.code == "000725"
    assert len(active_alerts()) == 1
    assert remove_alert(alert.id)
    assert len(active_alerts()) == 0


def test_condition_met():
    assert _condition_met("ABOVE", 5.9, 5.8)
    assert not _condition_met("ABOVE", 5.7, 5.8)
    assert _condition_met("BELOW", 5.7, 5.8)


def test_check_alerts_triggers(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_reach.daily_run.price_alerts.alerts_path", lambda: tmp_path / "alerts.json")
    add_alert(code="688008", target_price=190.0, condition="BELOW", name="澜起科技")
    monkeypatch.setattr(
        "agent_reach.daily_run.price_alerts._fetch_prices",
        lambda codes, settings=None: {"688008": 188.5},
    )
    from agent_reach.daily_run.price_alerts import check_price_alerts

    result = check_price_alerts(settings={"price_alerts": {"push_feishu": False}}, push=False)
    assert len(result.get("triggered") or []) == 1
    assert len(active_alerts()) == 0


def test_get_source_alignment_labels():
    assert get_source_alignment([70, 68]) == "偏多对齐"
    assert get_source_alignment([30, 28]) == "偏空对齐"
    assert get_source_alignment([70, 40]) == "显著分歧"
    assert get_source_alignment([55]) == "单源视图"


def test_build_symbol_sentiment_alignment():
    item = build_symbol_sentiment_alignment(
        "688008",
        snapshot={"code": "688008", "name": "澜起科技", "mss_final": 52},
        macro_signals={
            "portfolio_symbol_sentiment": [
                {"code": "688008", "name": "澜起科技", "posts": [{"title": "大涨突破利好"}]}
            ]
        },
        redfox={"matched": [{"code": "688008", "title": "科技强势反弹"}]},
        market_review={"emotion": {"rating": "中"}},
    )
    assert item["available_sources"] >= 2
    md = render_sentiment_alignment_markdown([item])
    assert "跨源舆情对齐" in md
    assert "688008" in md


def test_llm_provider_chain(monkeypatch):
    from agent_reach.daily_run import llm_chat

    monkeypatch.setattr(llm_chat, "resolve_chat_provider", lambda p: p == "deepseek")
    chain = llm_chat._provider_chain("auto")
    assert chain[0] == "deepseek"


def test_chat_json_fallback(monkeypatch):
    from agent_reach.daily_run import llm_chat

    calls = {"n": 0}

    def fake_text(**kwargs):
        calls["n"] += 1
        if kwargs.get("provider") == "deepseek":
            return None
        return '{"summary": "ok", "focus_points": ["a"]}'

    monkeypatch.setattr(llm_chat, "_provider_chain", lambda preferred="auto": ["deepseek", "groq"])
    monkeypatch.setattr(llm_chat, "_chat_completion_text", fake_text)
    out = llm_chat.chat_json(system="s", user="u", provider="auto")
    assert out is not None
    assert out.get("summary") == "ok"
    assert calls["n"] >= 2


def test_user_profile_sectors(tmp_path, monkeypatch):
    path = tmp_path / "user_profile.json"
    monkeypatch.setattr("agent_reach.daily_run.user_profile.user_profile_path", lambda: path)
    save_user_profile(
        {
            "risk_tolerance": "moderate",
            "preferred_sectors": ["半导体", "光通信"],
            "investment_goals": "growth",
        }
    )
    prof = load_user_profile()
    assert profile_sector_match("半导体设备", prof)
    boost = watchlist_profile_score_adjustment(
        {"sector": "半导体"},
        settings={"user_profile": {"enabled": True}},
        profile=prof,
    )
    assert boost > 0


def test_watchlist_candidate_affordable(monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.portfolio_manager.watchlist_per_trade_budget",
        lambda *a, **k: {
            "per_budget": 15_000,
            "deploy_ratio": 0.25,
            "min_cash_ratio": 0.1,
            "commission_rate": 0.0015,
        },
    )
    from agent_reach.daily_run.portfolio_manager import watchlist_candidate_affordable

    pf = {"holdings": [], "watchlist": [], "cash": 50_000, "total": 100_000}
    enriched = {
        "688981": {"code": "688981", "name": "中芯国际", "price": 119.0},
        "000725": {"code": "000725", "name": "京东方A", "price": 5.75},
    }
    settings = {"watchlist": {"require_affordable_lot": True}}
    ok_exp, _ = watchlist_candidate_affordable(pf, enriched, settings, "688981")
    ok_cheap, _ = watchlist_candidate_affordable(pf, enriched, settings, "000725")
    assert ok_exp is False
    assert ok_cheap is True


def test_job_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_reach.daily_run.job_checkpoint.step_checkpoint_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.job_checkpoint.today_shanghai",
        lambda: __import__("datetime").date(2026, 9, 20),
    )
    clear_checkpoint("close")
    assert not is_step_done("close", "symbol:688008")
    mark_step_done("close", "symbol:688008", summary={"code": "688008"})
    assert is_step_done("close", "symbol:688008")
    data = load_checkpoint("close")
    assert "symbol:688008" in (data.get("steps") or {})
