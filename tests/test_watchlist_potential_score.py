# -*- coding: utf-8
"""M10 — watchlist potential score (ambush ranking + Feishu one-liners)."""

from __future__ import annotations

from agent_reach.daily_run.watchlist_potential_score import (
    compute_watchlist_potential,
    format_watchlist_potential_one_liner,
    render_watchlist_potential_markdown,
    watchlist_potential_enabled,
)


def _settings(**overrides):
    wl = {
        "potential_score": {"enabled": True},
        "hot_topic_adjust_enabled": False,
    }
    wl.update(overrides.get("watchlist") or {})
    return {"watchlist": wl, "berkshire": {"quality_screen_watchlist": False}}


def test_potential_score_favors_low_position_and_mss_room():
    cand = {"code": "603986", "name": "兆易创新", "keywords": ["存储"]}
    row = {"mss_final": 48.0, "position_20d": 0.25, "change_pct": 0.5}
    low = compute_watchlist_potential(cand, row=row, settings=_settings(), base_mss=50.0)
    high_pos = compute_watchlist_potential(
        cand,
        row={**row, "position_20d": 0.92, "change_pct": 8.0},
        settings=_settings(),
        base_mss=50.0,
        hot_titles=["存储芯片暴涨"],
    )
    assert low.score > high_pos.score
    assert "潜力" in format_watchlist_potential_one_liner(low)


def test_hot_chase_penalty_when_on_hot_list_and_up_big():
    cand = {"code": "300308", "name": "中际旭创", "keywords": ["光模块"]}
    row = {"mss_final": 52.0, "position_20d": 0.5, "change_pct": 7.0}
    calm = compute_watchlist_potential(cand, row=row, settings=_settings(), hot_titles=[])
    chased = compute_watchlist_potential(
        cand, row=row, settings=_settings(), hot_titles=["光模块龙头涨停"]
    )
    assert calm.score > chased.score
    assert "hot_chase" in chased.components or chased.primary_reason == "热点追高"


def test_render_watchlist_potential_markdown_one_line_per_symbol():
    pf = {
        "watchlist": [
            {
                "code": "603986",
                "name": "兆易创新",
                "potential_score": 71.0,
                "potential_reason": "20日偏低",
            }
        ]
    }
    md = render_watchlist_potential_markdown(pf, {}, settings=_settings())
    assert "观察池潜力" in md
    assert "潜力 71 · 20日偏低" in md
    assert watchlist_potential_enabled(_settings())
