# -*- coding: utf-8 -*-
"""Tests for symbol name resolution helpers."""

from __future__ import annotations

import json
from pathlib import Path

from agent_reach.daily_run.berkshire.thesis_tracker import (
    build_thesis_from_snapshot,
    render_thesis_markdown,
    sync_thesis_from_snapshot,
)
from agent_reach.daily_run.report_push import render_close_sections
from agent_reach.daily_run.symbols import (
    format_symbol_reference,
    is_redundant_symbol_name,
    resolve_symbol_name,
    symbol_display_name,
)


def test_is_redundant_symbol_name():
    assert is_redundant_symbol_name("002273", "002273") is True
    assert is_redundant_symbol_name("002273 (002273)", "002273") is True
    assert is_redundant_symbol_name("水晶光电", "002273") is False


def test_resolve_symbol_name_prefers_portfolio_over_snapshot_code():
    pf = {"holdings": [], "watchlist": [{"code": "002273", "name": "水晶光电"}]}
    snap = {"code": "002273", "name": "002273"}
    assert resolve_symbol_name(pf, "002273", fallback=snap["name"], snapshot=snap) == "水晶光电"
    assert symbol_display_name(pf, "002273") == "水晶光电"


def test_format_symbol_reference_skips_duplicate_code():
    assert format_symbol_reference("002273", "002273") == "002273"
    assert format_symbol_reference("水晶光电", "002273") == "水晶光电(002273)"


def test_build_thesis_uses_watchlist_name():
    pf = {"holdings": [], "watchlist": [{"code": "002273", "name": "水晶光电"}]}
    snap = {"code": "002273", "name": "002273", "verdict": "观察", "mss_final": 49.16}
    doc = build_thesis_from_snapshot(snap, portfolio=pf)
    assert doc["name"] == "水晶光电"
    assert doc["core_thesis"].startswith("跟踪 水晶光电(002273)：")


def test_render_thesis_markdown_no_duplicate_code():
    md = render_thesis_markdown({"code": "002273", "name": "002273", "core_thesis": "x"})
    assert "**投资论文** · 002273" in md
    assert "(002273)" not in md.split("\n", 1)[0]


def test_sync_thesis_refreshes_stale_name(tmp_path, monkeypatch):
    from agent_reach.daily_run import berkshire

    monkeypatch.setattr(berkshire.config, "thesis_dir", lambda _s=None: tmp_path / "thesis")
    thesis_dir = tmp_path / "thesis"
    thesis_dir.mkdir(parents=True)
    (thesis_dir / "002273.json").write_text(
        json.dumps(
            {
                "code": "002273",
                "name": "002273",
                "core_thesis": "跟踪 002273(002273)：MSS 49 · 观察。观察池/候选。",
                "assumptions": [],
                "history": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pf = {"holdings": [], "watchlist": [{"code": "002273", "name": "水晶光电"}]}
    snap = {"code": "002273", "name": "002273", "mss_final": 49.16, "verdict": "观察", "price": 26.12}
    settings = {"berkshire": {"enabled": True, "thesis_tracker": True}}
    out = sync_thesis_from_snapshot(snap, settings=settings, portfolio=pf)
    doc = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
    assert doc["name"] == "水晶光电"
    assert doc["core_thesis"].startswith("跟踪 水晶光电(002273)：")


def test_daily_portfolio_section_title_uses_portfolio_label():
    sections = render_close_sections(
        verify_name="002273",
        verify_markdown="验证",
        portfolio_markdown="## 组合盈亏",
    )
    portfolio_sec = next(s for s in sections if s.category == "daily_portfolio")
    assert "· 组合" in portfolio_sec.title
    assert "002273" not in portfolio_sec.title
