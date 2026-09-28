# -*- coding: utf-8 -*-
"""CLI interface for daily-run mission control panel.

Subcommands:
- daily-run panel serve [--host 127.0.0.1] [--port 8788] [--open]
- daily-run panel export [--output path] [--open]
- daily-run panel status [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_reach.daily_run.panel.config import panel_cfg
from agent_reach.daily_run.panel.export import export_panel_html
from agent_reach.daily_run.panel.reader import PanelDataReader
from agent_reach.daily_run.settings import load_settings


def add_panel_subparser(p_daily_sub: argparse._SubParsersAction) -> None:
    """Register 'panel' subparser under 'daily-run'."""
    p_panel = p_daily_sub.add_parser(
        "panel",
        help="Interactive mission control dashboard & TSP quant visualization",
    )
    p_panel_sub = p_panel.add_subparsers(dest="panel_action", required=True)

    # 1. serve
    p_serve = p_panel_sub.add_parser("serve", help="Start live HTTP & SSE panel web server")
    p_serve.add_argument("--host", default="", help="Bind host (default: 127.0.0.1 or from settings)")
    p_serve.add_argument("--port", type=int, default=0, help="Bind port (default: 8788 or from settings)")
    p_serve.add_argument("--open", action="store_true", help="Open browser on startup")
    p_serve.add_argument("--db", default="", help="Override SQLite DB path")

    # 2. export
    p_export = p_panel_sub.add_parser("export", help="Export standalone self-contained HTML report")
    p_export.add_argument(
        "--output", "-o",
        default="",
        help="Target HTML output path (default: ~/.agent-reach/daily_run/panel_report.html)",
    )
    p_export.add_argument("--open", action="store_true", help="Open generated HTML in browser")
    p_export.add_argument("--db", default="", help="Override SQLite DB path")

    # 3. status
    p_status = p_panel_sub.add_parser("status", help="Show terminal status overview of the panel")
    p_status.add_argument("--json", action="store_true", help="Output full JSON state")
    p_status.add_argument("--db", default="", help="Override SQLite DB path")


def cmd_panel(args: argparse.Namespace) -> None:
    """Dispatch panel subcommands."""
    action = args.panel_action
    settings = load_settings()
    cfg = panel_cfg(settings)

    db_path = Path(args.db).expanduser() if getattr(args, "db", None) else None

    if action == "serve":
        try:
            from agent_reach.daily_run.panel.server import serve_panel
        except ImportError as exc:
            print("❌ panel serve 需要额外安装可选依赖 starlette 和 uvicorn。")
            print("   请运行: pip install starlette uvicorn")
            sys.exit(1)

        host = args.host or cfg.get("host") or "127.0.0.1"
        port = args.port or int(cfg.get("port") or 8788)
        open_browser = getattr(args, "open", False)
        serve_panel(host=host, port=port, open_browser=open_browser, db_path=db_path)
        return

    if action == "export":
        out_path = Path(args.output).expanduser() if getattr(args, "output", None) else None
        generated = export_panel_html(output_path=out_path, db_path=db_path)
        print(f"✅ 态势大屏离线 HTML 报告已生成: {generated}")
        if getattr(args, "open", False):
            import webbrowser
            webbrowser.open(f"file://{generated.resolve()}")
        return

    if action == "status":
        reader = PanelDataReader(db_path=db_path, settings=settings)
        state = reader.get_full_panel_state()
        if getattr(args, "json", False):
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return

        # Render Terminal Summary
        meta = state.get("meta", {})
        pf = state.get("portfolio", {})
        reg = state.get("regime", {})
        devs = state.get("deviations", [])
        intraday = state.get("intraday", {})

        print("=" * 68)
        print(f"  🎯 {meta.get('system_name')} (v{meta.get('version')})")
        print(f"  🕒 北京时间: {meta.get('beijing_time')}  |  盘口状态: {meta.get('market_status')}")
        print("=" * 68)

        print("\n[1. 资产与持仓组合]")
        print(f"  - 总资产估值: ¥{pf.get('total_equity', 0):,.2f}")
        print(f"  - 可用现金:   ¥{pf.get('cash', 0):,.2f} (仓位现金比: {pf.get('cash_ratio', 0):.1f}%)")
        print(f"  - 浮动盈亏:   ¥{pf.get('unrealized_pnl', 0):+,.2f} ({pf.get('unrealized_pnl_pct', 0):+.2f}%)")
        print(f"  - 当前持仓数: {pf.get('holdings_count', 0)} 只")
        for h in pf.get("holdings", []):
            pnl_sign = "+" if h.get("unrealized_pnl", 0) >= 0 else ""
            print(
                f"    • {h.get('name')}({h.get('code')}): {h.get('shares')}股 | "
                f"现价 ¥{h.get('price'):.2f} | 盈亏 {pnl_sign}¥{h.get('unrealized_pnl', 0):.2f} "
                f"({pnl_sign}{h.get('unrealized_pnl_pct', 0):.2f}%)"
            )

        print("\n[2. TSP 超短情绪与主线阵列]")
        print(f"  - 实时周期:   {reg.get('phase_label')} ({reg.get('description')})")
        print(f"  - 炸板率:     {reg.get('broken_board_rate', 0):.1f}% (全市场涨跌比: {reg.get('up_count', 0)} : {reg.get('down_count', 0)})")
        print(f"  - 连板天梯:   最高连板高度 {reg.get('max_limit_up_streak', 0)} 板")
        if reg.get("retreat_triggered"):
            print(f"  - 🛑 退潮急刹车: {reg.get('retreat_reason')}")
        print("  - 前五主线题材:")
        for idx, m in enumerate(reg.get("top_mainlines", [])[:5], start=1):
            print(f"    {idx}. 【{m.get('sector')}】强度: {m.get('score')}分 | 领涨: {m.get('leader_stock')} ({m.get('limit_up_count')}板)")

        print("\n[3. 交易所异动偏离监管雷达 (Top Alerts)]")
        warning_count = sum(1 for d in devs if d.get("risk_level") in ("warning", "critical"))
        print(f"  - 监测标的数: {len(devs)} 只 (预警标的: {warning_count} 只)")
        for d in devs[:5]:
            flag = "🛑[高危]" if d.get("risk_level") == "critical" else ("⚠️[预警]" if d.get("risk_level") == "warning" else "🟢[安全]")
            print(
                f"    {flag} {d.get('name')}({d.get('code')}): 3日累涨 {d.get('cumulative_3d_pct'):+.1f}% / 门槛 ±{d.get('threshold_3d_pct'):.0f}% | "
                f"安全垫剩余: {d.get('distance_to_limit_pct'):.1f}%"
            )

        print("\n[4. 交易日内 10 次量化扫描进度]")
        cycles = intraday.get("completed_cycles", [])
        print(f"  - 进度: {len(cycles)}/10 周期已完成 ({', '.join(cycles) if cycles else '等待开盘'})")
        print("=" * 68 + "\n")
        return

    print("Usage: agent-reach daily-run panel {serve|export|status}")
    sys.exit(1)
