# -*- coding: utf-8
"""Tests for quant chain repair helpers."""

from datetime import date

from agent_reach.daily_run.quant_repair import portfolio_summary_from_handoff


def test_portfolio_summary_from_handoff_parses_narrative():
    handoff = {
        "portfolio_total": 105000,
        "tomorrow_focus": [
            {"kind": "narrative", "text": "组合当日盈亏 ¥-457（-0.43%）"},
        ],
    }
    summary = portfolio_summary_from_handoff(handoff)
    assert summary["end_total"] == 105000
    assert summary["daily_pnl"] == -457
    assert summary["daily_pnl_pct"] == -0.43


def test_repair_close_handoff_seeds(tmp_path, monkeypatch):
    from agent_reach.daily_run import quant_calibration as qc_mod
    from agent_reach.daily_run.quant_repair import repair_close_handoff_seeds

    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    monkeypatch.setattr("agent_reach.daily_run.quant_repair._handoff_dir", lambda: handoff_dir)
    monkeypatch.setattr(qc_mod, "_handoff_dir", lambda: handoff_dir)
    monkeypatch.setattr(
        "agent_reach.daily_run.close_morning_handoff._HANDOFF_DIR",
        handoff_dir,
    )

    day = date(2026, 8, 31)
    payload = {
        "close_date": day.isoformat(),
        "portfolio_total": 100000,
        "tomorrow_focus": [{"kind": "narrative", "text": "组合当日盈亏 ¥-100（-0.10%）"}],
    }
    import json

    (handoff_dir / f"close_{day.isoformat()}.json").write_text(
        json.dumps(payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = repair_close_handoff_seeds(settings={"quant_calibration": {"enabled": True}})
    assert day.isoformat() in result["repaired"]
    saved = json.loads((handoff_dir / f"close_{day.isoformat()}.json").read_text(encoding="utf-8"))
    assert saved["next_day_session_seed"]["regime"] == "defensive"
