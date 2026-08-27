# -*- coding: utf-8
"""Tests for close code walkthrough and bug fixes."""

from agent_reach.daily_run.close_code_review import (
    CodeReviewResult,
    render_code_review_markdown,
    run_close_code_review,
)
from agent_reach.daily_run.settings import load_settings


def test_auto_fix_watchlist_overlap():
    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 61000,
        "cash_ratio": 0.61,
        "holdings": [{"code": "688008", "name": "澜起科技", "shares": 100, "days_held": 5}],
        "watchlist": [
            {"code": "688008", "name": "澜起科技"},
            {"code": "603986", "name": "兆易创新"},
        ],
    }
    snapshot = {"mss_final": 48, "watchlist": portfolio["watchlist"]}

    result = run_close_code_review(
        portfolio=portfolio,
        snapshot=snapshot,
        settings=settings,
    )
    assert result.portfolio_changed is True
    codes = {w["code"] for w in result.portfolio["watchlist"]}
    assert "688008" not in codes
    assert any("重复" in f for f in result.fixes_applied)


def test_render_code_review_markdown():
    settings = load_settings()
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
    )
    md = render_code_review_markdown(result)
    assert "代码走读" in md


def test_code_review_from_dict_rehydrates_findings():
    raw = CodeReviewResult(
        findings=[],
        fixes_applied=["fix one"],
    ).to_dict()
    raw["findings"] = [
        {
            "area": "portfolio",
            "severity": "medium",
            "title": "示例 finding",
            "detail": "detail text",
            "fixed": False,
            "fix_note": "",
        }
    ]
    restored = CodeReviewResult.from_dict(raw)
    md = render_code_review_markdown(restored)
    assert "示例 finding" in md
    assert restored.fixes_applied == ["fix one"]


def test_detect_cash_ratio_mismatch():
    settings = load_settings()
    settings = {
        **settings,
        "harness": {**(settings.get("harness") or {}), "enabled": False, "runtime_overlay": False},
    }
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.61,
        "holdings": [],
        "watchlist": [],
    }
    result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.portfolio_changed is True
    cash = float(result.portfolio["cash"])
    total = float(result.portfolio["total"])
    assert abs(float(result.portfolio["cash_ratio"]) - cash / total) < 0.001


def test_auto_fix_cash_vs_ledger_recalcs_total(tmp_path, monkeypatch):
    """H1: the cash-vs-ledger auto-fix must recompute `total`, not just `cash`/
    `cash_ratio` — otherwise total = cash + MV drifts out of its own identity
    by exactly the corrected amount."""
    import json

    from agent_reach.daily_run import workflows

    baseline_path = tmp_path / "last_morning.json"
    baseline_path.write_text(
        json.dumps({"portfolio": {"cash": 50000.0, "holdings": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workflows, "_default_baseline_path", lambda: baseline_path)

    settings = load_settings()
    settings = {
        **settings,
        "harness": {**(settings.get("harness") or {}), "enabled": False, "runtime_overlay": False},
    }
    # No ledger trades today, no capital events -> expected end cash = morning
    # cash (50000). portfolio.json on disk claims cash=60000 (drift +10000) and
    # a stale, already-inconsistent `total` (999999, unrelated to cash/MV) —
    # deliberately NOT `old_total - drift`, so a naive "shift total by drift"
    # fix (999999 - 10000 = 989999) would still be wrong; only a genuine
    # recompute (cash + MV) lands on the correct 70000.
    portfolio = {
        "total": 999999.0,
        "cash": 60000.0,
        "cash_ratio": 0.5,
        "holdings": [{"code": "000725", "name": "京东方A", "shares": 1000, "cost": 4.0}],
        "watchlist": [],
    }
    snapshot = {
        "portfolio": {
            "holdings": [{"code": "000725", "name": "京东方A", "price": 20.0}],
        },
    }
    result = run_close_code_review(portfolio=portfolio, snapshot=snapshot, settings=settings)

    assert result.portfolio_changed is True
    fixed = result.portfolio
    assert fixed["cash"] == 50000.0
    # total must reflect cash(50000) + MV(1000 * 20.0 = 20000) = 70000.
    assert fixed["total"] == 70000.0
    assert abs(fixed["cash"] / fixed["total"] - fixed["cash_ratio"]) < 1e-3
    assert any("ledger 不一致" in f.title for f in result.findings)


def test_pnl_history_gap_flagged(monkeypatch):
    """M2: recent trading days missing from pnl_history.jsonl surface as a
    (non-auto-fixable) finding, since `cumulative_pnl` silently skips them."""
    from datetime import date

    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        lambda: date(2026, 8, 24),
    )
    monkeypatch.setattr(
        "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
        lambda: {
            "2026-08-17",
            "2026-08-18",
            "2026-08-19",
            "2026-08-20",
            "2026-08-21",
            "2026-08-24",
        },
    )
    settings = load_settings()
    settings["close_code_review"] = {"walk_on_close": False, "run_smoke_tests": False}
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
    )
    gap_findings = [f for f in result.findings if f.area == "pnl_history"]
    assert gap_findings
    assert gap_findings[0].fixed is False
    assert "2026-08-21" in gap_findings[0].detail


def test_auto_fix_stale_days_held():
    from datetime import date
    from unittest.mock import patch

    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.5,
        "holdings": [
            {
                "code": "000725",
                "name": "京东方A",
                "shares": 1000,
                "cost": 6.0,
                "acquired_date": "2026-07-24",
                "days_held": 0,
            }
        ],
        "watchlist": [],
    }
    with patch(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        return_value=date(2026, 7, 27),
    ):
        result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.portfolio_changed is True
    assert result.portfolio["holdings"][0]["days_held"] == 1
    assert any("days_held" in f for f in result.fixes_applied)


def test_auto_fix_backfills_missing_acquired_date():
    """M1: legacy holdings with only a days_held counter get acquired_date
    backfilled (reconstructed via the trading calendar) so future T+1 checks
    use the more reliable acquired_date path instead of the raw counter."""
    from datetime import date
    from unittest.mock import patch

    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.5,
        "holdings": [
            {
                "code": "000725",
                "name": "京东方A",
                "shares": 1000,
                "cost": 6.0,
                "days_held": 3,
            }
        ],
        "watchlist": [],
    }
    with patch(
        "agent_reach.daily_run.trade_calendar._load_trade_dates_akshare",
        return_value=set(),
    ), patch(
        "agent_reach.daily_run.trade_calendar.today_shanghai",
        return_value=date(2026, 8, 24),
    ):
        result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.portfolio_changed is True
    acquired = result.portfolio["holdings"][0].get("acquired_date")
    assert acquired == "2026-08-19"
    findings = [f for f in result.findings if "days_held 计数器" in f.title]
    assert findings and findings[0].fixed is True


def test_no_backfill_when_auto_fix_disabled():
    from datetime import date
    from unittest.mock import patch

    settings = load_settings()
    settings["close_code_review"] = {"auto_fix_portfolio": False}
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.5,
        "holdings": [
            {"code": "000725", "name": "京东方A", "shares": 1000, "cost": 6.0, "days_held": 3}
        ],
        "watchlist": [],
    }
    with patch("agent_reach.daily_run.trade_calendar.today_shanghai", return_value=date(2026, 8, 24)):
        result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.portfolio["holdings"][0].get("acquired_date") is None


def test_duplicate_scan_ids_reported():
    settings = load_settings()
    settings.setdefault("close_code_review", {})["walk_on_close"] = False
    settings["close_code_review"]["run_smoke_tests"] = False
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
        scans=[
            {"scan_id": "S1", "mss_final": 50},
            {"scan_id": "S1", "mss_final": 49},
        ],
    )
    assert any("重复" in f.title for f in result.findings)


def test_code_review_disabled_skips_findings():
    settings = load_settings()
    settings["close_code_review"] = {"enabled": False}
    portfolio = {
        "total": 100000,
        "cash": 61000,
        "cash_ratio": 0.99,
        "holdings": [],
        "watchlist": [{"code": "688008", "name": "澜起科技"}],
    }
    result = run_close_code_review(portfolio=portfolio, snapshot={}, settings=settings)
    assert result.findings == []
    assert result.portfolio_changed is False


def test_auto_fix_abnormal_cost():
    settings = load_settings()
    portfolio = {
        "total": 100000,
        "cash": 50000,
        "cash_ratio": 0.5,
        "holdings": [{"code": "002583", "name": "海能达", "shares": 1000, "cost": 28.4}],
        "watchlist": [],
    }
    snapshot = {
        "code": "002583",
        "portfolio": {
            "holdings": [
                {"code": "002583", "price": 7.98, "quote_source": "xueqiu"},
            ]
        },
    }
    result = run_close_code_review(portfolio=portfolio, snapshot=snapshot, settings=settings)
    assert result.portfolio_changed is True
    assert result.portfolio["holdings"][0]["cost"] == 7.98
    assert any("cost" in f.lower() or "成本" in f for f in result.fixes_applied)


def test_harness_overlay_missing_when_runtime_absent():
    settings = load_settings()
    settings.setdefault("harness", {})["enabled"] = True
    settings["harness"]["threshold_evolution_mode"] = "harness"
    settings.pop("harness_runtime", None)
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
    )
    assert any(f.area == "harness" and "overlay" in f.title for f in result.findings)


def test_harness_defensive_signal_threshold_mismatch(monkeypatch):
    settings = load_settings()
    from agent_reach.daily_run.settings import effective_settings

    settings = effective_settings(settings)
    settings["thresholds"]["macro_veto"] = 40.0
    settings.setdefault("harness_runtime", {})["trade_signals"] = {
        "defensive_trim": True,
        "mss_forecast_miss": True,
        "deviation_active": True,
    }
    monkeypatch.setattr(
        "agent_reach.daily_run.harness_policy.resolve_harness_trade_signals",
        lambda *args, **kwargs: {
            "defensive_trim": True,
            "mss_forecast_miss": True,
            "deviation_active": True,
            "kronos_bullish": {},
            "kronos_bearish": {},
        },
    )
    result = run_close_code_review(
        portfolio={"holdings": [], "watchlist": [], "cash": 1, "total": 1, "cash_ratio": 1},
        snapshot={},
        settings=settings,
    )
    assert any(f.area == "harness" and "macro_veto" in f.title for f in result.findings)
