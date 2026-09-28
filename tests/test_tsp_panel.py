# -*- coding: utf-8 -*-
"""Unit tests for TSP mission control live dashboard and API panel."""

import json
import sqlite3
from pathlib import Path
import pytest

from agent_reach.daily_run.panel.config import (
    panel_card_link_enabled,
    panel_cfg,
    panel_url,
)
from agent_reach.daily_run.panel.export import export_panel_html
from agent_reach.daily_run.panel.reader import PanelDataReader
from agent_reach.daily_run.tsp.intraday_sentinel import format_tsp_intraday_card_markdown

try:
    from starlette.testclient import TestClient
    from agent_reach.daily_run.panel.server import PanelServer
    HAS_STARLETTE = True
except ImportError:
    HAS_STARLETTE = False
    TestClient = None  # type: ignore
    PanelServer = None  # type: ignore


@pytest.fixture
def isolated_panel_env(tmp_path: Path):
    """Create an isolated test environment with a fresh SQLite DB and portfolio.json."""
    data_root = tmp_path / "daily_run"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "test_panel.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            source TEXT NOT NULL,
            cash REAL,
            total REAL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE positions (
            code TEXT PRIMARY KEY,
            name TEXT,
            shares INTEGER,
            cost REAL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE l0_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            at TEXT NOT NULL,
            source_path TEXT,
            payload_json TEXT NOT NULL,
            dedupe_key TEXT UNIQUE,
            distilled_at TEXT
        );
        """
    )

    # Insert mock snapshot
    conn.execute(
        """
        INSERT INTO portfolio_snapshots (at, source, cash, total, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "2026-09-28T10:00:00Z",
            "test_source",
            50000.0,
            100000.0,
            json.dumps({"cash": 50000.0, "total": 100000.0}),
        ),
    )

    # Insert mock position
    conn.execute(
        """
        INSERT INTO positions (code, name, shares, cost, payload_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "688008",
            "澜起科技",
            100,
            200.0,
            json.dumps({"price": 220.0, "change_pct": 5.0, "days_held": 10}),
            "2026-09-28T10:00:00Z",
        ),
    )

    # Insert mock events
    conn.execute(
        """
        INSERT INTO l0_events (kind, at, payload_json)
        VALUES (?, ?, ?)
        """,
        (
            "intraday_scan",
            "2026-09-28T10:05:00Z",
            json.dumps(
                {
                    "scan_id": "S1",
                    "code": "688008",
                    "name": "澜起科技",
                    "price": 220.0,
                    "mss_final": 58.5,
                    "verdict": "买入",
                    "confidence": "高",
                    "audit_passed": True,
                }
            ),
        ),
    )

    conn.execute(
        """
        INSERT INTO l0_events (kind, at, payload_json)
        VALUES (?, ?, ?)
        """,
        (
            "trade",
            "2026-09-28T10:10:00Z",
            json.dumps(
                {
                    "trade_id": "T1",
                    "decision_action": "buy",
                    "actions": [
                        {
                            "side": "buy",
                            "code": "688008",
                            "name": "澜起科技",
                            "shares": 100,
                            "price": 220.0,
                            "amount": 22000.0,
                            "reasoning": "TSP主线强共振开仓",
                        }
                    ],
                }
            ),
        ),
    )

    conn.commit()
    conn.close()

    # Also create portfolio.json as backup
    portfolio_file = data_root / "portfolio.json"
    portfolio_file.write_text(
        json.dumps(
            {
                "cash": 50000.0,
                "total": 100000.0,
                "watchlist": ["000001", "300750"],
                "holdings": [
                    {
                        "code": "688008",
                        "name": "澜起科技",
                        "shares": 100,
                        "cost": 200.0,
                        "price": 220.0,
                        "change_pct": 5.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    yield {"data_root": data_root, "db_path": db_path}


def test_panel_config():
    """Verify panel config resolution and defaults."""
    cfg = panel_cfg()
    assert cfg["enabled"] is True
    assert cfg["port"] == 8788
    assert "url" in cfg
    url = panel_url()
    assert "reports/" in url
    assert "index" in url
    assert "github.io" in url
    assert "reports/index.html" in url
    assert panel_card_link_enabled() is True

    from agent_reach.daily_run.panel.config import build_public_report_url

    pages = build_public_report_url(
        "reports/index.html",
        settings={"panel": {"url_mode": "pages", "github_repo": "zjk1984/Agent-Reach", "branch": "main"}},
    )
    assert pages == "https://zjk1984.github.io/Agent-Reach/reports/index.html"
    jsdelivr = build_public_report_url(
        "reports/index.html",
        settings={"panel": {"url_mode": "jsdelivr", "github_repo": "zjk1984/Agent-Reach", "branch": "main"}},
    )
    assert jsdelivr.startswith("https://cdn.jsdelivr.net/gh/zjk1984/Agent-Reach@main/reports/index.html")

    # Custom override
    custom_cfg = {"panel": {"url": "https://quant.example.com", "card_link_enabled": False}}
    assert panel_url(custom_cfg) == "https://quant.example.com"
    assert panel_card_link_enabled(custom_cfg) is False


def test_panel_reader(isolated_panel_env):
    """Verify PanelDataReader extracts portfolio, regime, events, and deviations."""
    env = isolated_panel_env
    reader = PanelDataReader(db_path=env["db_path"], data_root=env["data_root"])

    # 1. Portfolio
    pf = reader.get_portfolio_status()
    assert pf["cash"] == 50000.0
    assert pf["total_equity"] == 100000.0
    assert pf["holdings_count"] == 1
    h0 = pf["holdings"][0]
    assert h0["code"] == "688008"
    assert h0["unrealized_pnl"] == 2000.0  # (220 - 200) * 100
    assert h0["unrealized_pnl_pct"] == 10.0

    # 2. TSP Regime
    regime = reader.get_tsp_regime()
    assert "phase" in regime
    assert "phase_label" in regime
    assert "broken_board_rate" in regime
    assert "top_mainlines" in regime

    # 3. Deviations
    devs = reader.get_deviation_radar()
    assert len(devs) >= 1
    d0 = devs[0]
    assert "distance_to_limit_pct" in d0
    assert "threshold_3d_pct" in d0
    assert "risk_level" in d0

    # 4. Events
    events = reader.get_recent_events(limit=10)
    assert len(events) == 2
    assert any(e["kind"] == "trade" for e in events)
    assert any(e["kind"] == "intraday_scan" for e in events)

    # 5. Full state
    full = reader.get_full_panel_state()
    assert "meta" in full
    assert full["meta"]["db_connected"] is True
    assert "history_reports" in full["meta"]
    assert "portfolio" in full
    assert "regime" in full
    assert "deviations" in full
    assert "events" in full
    assert "sparkline" in full["intraday"]
    assert len(full["intraday"]["sparkline"]) >= 1
    sp0 = full["intraday"]["sparkline"][0]
    assert sp0["cycle"] == "S1"
    assert sp0["mss"] == 58.5
    assert sp0["verdict"] == "买入"


def test_panel_server_endpoints(isolated_panel_env):
    """Verify Starlette REST endpoints via TestClient (skipped if starlette not installed)."""
    if not HAS_STARLETTE:
        pytest.skip("starlette/uvicorn optional dependencies not installed")
    env = isolated_panel_env
    reader = PanelDataReader(db_path=env["db_path"], data_root=env["data_root"])
    server = PanelServer(reader=reader)

    with TestClient(server.app) as client:
        # GET /
        resp_index = client.get("/")
        assert resp_index.status_code == 200
        assert "text/html" in resp_index.headers["content-type"]
        assert "Agent Reach Daily-Run" in resp_index.text

        # GET /api/status
        resp_status = client.get("/api/status")
        assert resp_status.status_code == 200
        data_status = resp_status.json()
        assert data_status["cash"] == 50000.0

        # GET /api/regime
        resp_regime = client.get("/api/regime")
        assert resp_regime.status_code == 200
        data_regime = resp_regime.json()
        assert "phase" in data_regime

        # GET /api/deviations
        resp_dev = client.get("/api/deviations")
        assert resp_dev.status_code == 200
        assert isinstance(resp_dev.json(), list)

        # GET /api/events
        resp_events = client.get("/api/events")
        assert resp_events.status_code == 200
        assert len(resp_events.json()) == 2

        # GET /api/full
        resp_full = client.get("/api/full")
        assert resp_full.status_code == 200
        data_full = resp_full.json()
        assert data_full["portfolio"]["cash"] == 50000.0


def test_panel_export_html(isolated_panel_env, tmp_path):
    """Verify exporting standalone HTML report."""
    env = isolated_panel_env
    out_file = tmp_path / "exported_report.html"
    result = export_panel_html(
        output_path=out_file,
        db_path=env["db_path"],
        data_root=env["data_root"],
    )
    assert result.exists()
    assert result == out_file
    content = result.read_text(encoding="utf-8")
    assert "__INITIAL_PANEL_DATA__" in content
    assert "__STATIC_EXPORT__" in content
    assert "Agent Reach Daily-Run" in content


def test_feishu_card_link_in_intraday():
    """Verify that format_tsp_intraday_card_markdown embeds panel link at the very top."""
    card_lines = format_tsp_intraday_card_markdown(
        "688008",
        symbol_data={"code": "688008", "name": "澜起科技", "industry": "半导体"},
        settings={
            "tsp_quant": {"enabled": True, "intraday": {"card_display_enabled": True}},
            "panel": {"enabled": True, "card_link_enabled": True, "url": "auto"},
        },
    )
    assert len(card_lines) > 0
    assert card_lines[0].startswith("🖥️ 实时大屏：")
    assert "reports/" in card_lines[0]
    assert "index" in card_lines[0]
    text = "\n".join(card_lines)
    assert "TSP 量化哨兵" in text


def test_find_latest_report_file_resolution(tmp_path):
    """Verify find_latest_report_file discovers newest file by timestamp or falls back to backup."""
    from agent_reach.daily_run.panel.config import find_latest_report_file, panel_url

    rep_dir = tmp_path / "reports"
    rep_dir.mkdir(parents=True)
    bak_dir = rep_dir / "backup"
    bak_dir.mkdir(parents=True)

    # 1. Empty reports dir -> None
    assert find_latest_report_file(reports_dir=rep_dir) is None

    # 2. Only backup dir has files
    bak_file = bak_dir / "index_20260928_100000.html"
    bak_file.write_text("<html>backup</html>", encoding="utf-8")
    found_bak = find_latest_report_file(reports_dir=rep_dir)
    assert found_bak is not None
    assert found_bak.name == "index_20260928_100000.html"

    # 3. reports dir has newer files
    f1 = rep_dir / "index_20260928_140000.html"
    f1.write_text("<html>14:00</html>", encoding="utf-8")
    f2 = rep_dir / "index_20260928_150000.html"
    f2.write_text("<html>15:00</html>", encoding="utf-8")

    latest = find_latest_report_file(reports_dir=rep_dir)
    assert latest is not None
    assert latest.name == "index_20260928_150000.html"

    # 4. Check panel_url resolution with custom reports_dir (local fallback when remote unknown)
    from unittest.mock import patch

    url = panel_url(
        reports_dir=rep_dir,
        settings={"panel": {"url_mode": "pages", "github_repo": "zjk1984/Agent-Reach"}},
    )
    assert url == "https://zjk1984.github.io/Agent-Reach/reports/index.html"


def test_prepend_panel_card_header():
    """Verify prepending header at line 0 and deduplicating old panel links."""
    from agent_reach.daily_run.panel.config import prepend_panel_card_header

    settings = {"panel": {"enabled": True, "card_link_enabled": True}}

    # Standard markdown without header
    raw_md = "## 标题\n内容正文"
    prepended = prepend_panel_card_header(raw_md, settings=settings)
    lines = prepended.split("\n")
    assert lines[0].startswith("🖥️ 实时大屏：")
    assert any(line.startswith("📡 数据源：") for line in lines)
    assert "## 标题" in prepended

    # Legacy markdown with panel link at bottom
    legacy_md = "## 标题\n内容正文\n- 🖥️ 实时大屏：[http://127.0.0.1:8788](http://127.0.0.1:8788)\n- 其它条目"
    cleaned = prepend_panel_card_header(legacy_md, settings=settings)
    assert cleaned.count("实时大屏") == 1
    assert cleaned.count("📡 数据源：") == 1
    assert cleaned.split("\n")[0].startswith("🖥️ 实时大屏：")
    assert "http://127.0.0.1:8788" not in cleaned
    assert "- 其它条目" in cleaned

    legacy_with_prov = legacy_md + "\n📡 数据源：D1✓ D2· D3· D4· D5· D6✓"
    cleaned_prov = prepend_panel_card_header(legacy_with_prov, settings=settings)
    assert cleaned_prov.count("📡 数据源：") == 1


def test_panel_cli(isolated_panel_env, capsys, tmp_path):
    """Verify CLI dispatch for panel status and export."""
    from argparse import Namespace
    from agent_reach.daily_run.panel_cli import cmd_panel

    env = isolated_panel_env

    # 1. Test status --json
    args_json = Namespace(
        panel_action="status",
        json=True,
        db=str(env["db_path"]),
    )
    cmd_panel(args_json)
    captured = capsys.readouterr()
    assert "total_equity" in captured.out
    assert "50000" in captured.out

    # 2. Test status formatted terminal output
    args_status = Namespace(
        panel_action="status",
        json=False,
        db=str(env["db_path"]),
    )
    cmd_panel(args_status)
    captured = capsys.readouterr()
    assert "Daily-Run Mission Control" in captured.out
    assert "资产与持仓组合" in captured.out
    assert "TSP 超短情绪" in captured.out

    # 3. Test export
    export_path = tmp_path / "cli_report.html"
    args_export = Namespace(
        panel_action="export",
        output=str(export_path),
        open=False,
        db=str(env["db_path"]),
    )
    cmd_panel(args_export)
    captured = capsys.readouterr()
    assert "离线 HTML 报告已生成" in captured.out
    assert export_path.exists()

    # 4. Test publish via CLI (no-push)
    rep_dir = tmp_path / "cli_reports"
    args_publish = Namespace(
        panel_action="publish",
        reports_dir=str(rep_dir),
        backup_dir=str(rep_dir / "backup"),
        no_push=True,
        job="morning",
        db=str(env["db_path"]),
    )
    cmd_panel(args_publish)
    captured = capsys.readouterr()
    assert "态势大屏报告已生成并发布" in captured.out
    index_files = list(rep_dir.glob("index_*.html"))
    assert len(index_files) == 1


def test_publish_panel_report_archives_and_generates(isolated_panel_env, tmp_path):
    """Verify publish_panel_report generates index_<timestamp>.html and archives previous reports into backup/."""
    from agent_reach.daily_run.panel.publisher import publish_panel_report

    env = isolated_panel_env
    rep_dir = tmp_path / "reports"
    bak_dir = rep_dir / "backup"

    # First run: generates reports/index_<timestamp>.html with no previous archive
    res1 = publish_panel_report(
        reports_dir=rep_dir,
        backup_dir=bak_dir,
        db_path=env["db_path"],
        data_root=env["data_root"],
        push_git=False,
        job="intraday",
    )
    assert res1["success"] is True
    assert res1["archived_count"] == 0
    report_file_1 = Path(res1["report_path"])
    assert report_file_1.exists()
    assert report_file_1.name.startswith("index_")
    assert report_file_1.suffix == ".html"
    first_content = report_file_1.read_text(encoding="utf-8")
    assert "__INITIAL_PANEL_DATA__" in first_content
    stable_alias = rep_dir / "index.html"
    assert stable_alias.exists()
    assert stable_alias.read_text(encoding="utf-8") == first_content

    # Second run: archives first index_<ts>.html into reports/backup/, generates fresh index_<ts>.html
    res2 = publish_panel_report(
        reports_dir=rep_dir,
        backup_dir=bak_dir,
        db_path=env["db_path"],
        data_root=env["data_root"],
        push_git=False,
        job="close",
    )
    assert res2["success"] is True
    assert res2["archived_count"] >= 1
    archived_names = {Path(p).name for p in res2["archived"]}
    assert report_file_1.name in archived_names
    archived_file = Path(next(p for p in res2["archived"] if Path(p).name == report_file_1.name))
    assert archived_file.exists()
    assert archived_file.parent == bak_dir

    report_file_2 = Path(res2["report_path"])
    assert report_file_2.exists()
    assert report_file_2.name.startswith("index_")
    assert len(list(rep_dir.glob("index_*.html"))) == 1


def test_list_recent_report_snapshots(tmp_path):
    """Verify list_recent_report_snapshots returns structured snapshot items."""
    from agent_reach.daily_run.panel.config import list_recent_report_snapshots

    rep_dir = tmp_path / "reports"
    bak_dir = rep_dir / "backup"
    rep_dir.mkdir(parents=True, exist_ok=True)
    bak_dir.mkdir(parents=True, exist_ok=True)

    # Empty initially
    assert list_recent_report_snapshots(reports_dir=rep_dir) == []

    # Create dummy reports
    (rep_dir / "index_20260928_150000.html").write_text("<html>latest</html>", encoding="utf-8")
    (bak_dir / "index_20260928_140000.html").write_text("<html>old1</html>", encoding="utf-8")
    (bak_dir / "index_20260928_130000.html").write_text("<html>old2</html>", encoding="utf-8")

    items = list_recent_report_snapshots(reports_dir=rep_dir)
    assert len(items) == 3
    # Top item should be the latest in reports/
    assert items[0]["filename"] == "index_20260928_150000.html"
    assert items[0]["is_backup"] is False
    assert "(最新)" in items[0]["label"]
    assert "url" in items[0]
    assert items[1]["is_backup"] is True
    assert items[2]["is_backup"] is True




