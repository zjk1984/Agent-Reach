# -*- coding: utf-8
"""Interactive REPL for ad-hoc daily-run research (AutoHedge-inspired, dry-run default)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

RECENT_FILE = Path.home() / ".agent-reach" / "daily_run" / "recent_tasks.txt"
MAX_RECENT = 5

console = Console()

TIPS = [
    "输入自然语言 task（如：分析中际旭创与工业富联，50万仓位）",
    "输入 quit / exit 退出",
    "输入 help / ? 查看帮助",
    "默认 dry-run：不推送飞书、不写 portfolio",
]


def _get_recent_tasks() -> list[str]:
    if not RECENT_FILE.exists():
        return []
    try:
        lines = RECENT_FILE.read_text(encoding="utf-8").strip().splitlines()
        return [ln.strip() for ln in lines[-MAX_RECENT:] if ln.strip()]
    except OSError:
        return []


def _append_recent(task: str) -> None:
    try:
        RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        recent = _get_recent_tasks()
        if task in recent:
            recent.remove(task)
        recent.append(task)
        RECENT_FILE.write_text("\n".join(recent[-MAX_RECENT:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def render_welcome(*, version: str = "") -> None:
    recent = _get_recent_tasks()
    left = Text.assemble(
        ("Daily-run REPL", "bold orange1"),
        "\n\n",
        ("v" + version if version else "adhoc", "dim"),
    )
    right_lines = ["Tips"] + TIPS
    if recent:
        right_lines.append("")
        right_lines.append("Recent")
        right_lines.extend(recent[-3:])
    right = Text("\n".join(right_lines), style="dim")
    console.print(
        Panel(
            Text.assemble(left, "\n\n", right),
            title="Agent Reach · daily-run repl",
            border_style="cyan",
        )
    )


def run_repl_task(
    task: str,
    *,
    dry_run: bool = True,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute one ad-hoc research task; returns pipeline payload."""
    from agent_reach.daily_run.agent_pipeline import (
        build_agent_trace,
        build_pipeline_handoff,
        discover_symbols_from_task,
    )
    from agent_reach.daily_run.pipeline import evaluate_snapshot
    from agent_reach.daily_run.plugins.loader import run_experts
    from agent_reach.daily_run.settings import effective_settings, load_settings
    from agent_reach.daily_run.snapshot_builder import load_portfolio

    cfg = effective_settings(settings or load_settings())
    pf = load_portfolio(settings=cfg)
    codes = discover_symbols_from_task(task, portfolio=pf, settings=cfg)
    if not codes:
        primary = str(pf.get("primary_code") or "").strip()
        if primary:
            codes = [primary.zfill(6)[-6:]]
    if not codes:
        raise ValueError("未能从 task 解析标的，请在 task 中写 6 位代码或持仓/观察池名称")

    code = codes[0]
    name = code
    for row in list(pf.get("holdings") or []) + list(pf.get("watchlist") or []):
        if str(row.get("code") or "").zfill(6)[-6:] == code:
            name = str(row.get("name") or code)
            break

    snapshot: dict[str, Any] = {
        "code": code,
        "name": name,
        "report_type": "repl",
        "portfolio": pf,
        "watchlist": pf.get("watchlist") or [],
        "task": task,
    }
    enriched = run_experts(snapshot, cfg)
    evaluation = evaluate_snapshot(enriched, cfg)
    pipeline = build_pipeline_handoff(
        enriched,
        evaluation,
        workflow="repl",
        task=task,
    )
    trace = build_agent_trace(enriched, evaluation, workflow="repl")
    return {
        "dry_run": dry_run,
        "codes": codes,
        "pipeline_handoff": pipeline,
        "agent_trace": trace,
        "evaluation": evaluation,
        "report": evaluation.get("report") or {},
    }


def _format_result(payload: dict[str, Any]) -> str:
    report = payload.get("report") or {}
    pipeline = payload.get("pipeline_handoff") or {}
    execution = pipeline.get("execution_intent") or {}
    lines = [
        f"codes: {', '.join(payload.get('codes') or [])}",
        f"verdict: {report.get('verdict')}  MSS={report.get('mss_final')}",
        f"action: {execution.get('action')} blocked={execution.get('blocked')}",
        "",
        json.dumps(pipeline, ensure_ascii=False, indent=2)[:3500],
    ]
    return "\n".join(lines)


def run_repl(*, version: str = "") -> int:
    render_welcome(version=version)
    while True:
        try:
            console.print(Text("> ", style="bold cyan"), end="")
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见。[/]")
            return 0

        if not line:
            continue
        lower = line.lower()
        if lower in ("quit", "exit", "q"):
            console.print("[dim]再见。[/]")
            return 0
        if lower in ("help", "?", "h"):
            for tip in TIPS:
                console.print(f"  [dim]·[/] {tip}")
            continue

        _append_recent(line)
        try:
            console.print("[dim]Running (dry-run)…[/]")
            result = run_repl_task(line, dry_run=True)
            console.print(
                Panel(
                    _format_result(result),
                    title="Pipeline result",
                    border_style="green",
                )
            )
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/]")
    return 0
