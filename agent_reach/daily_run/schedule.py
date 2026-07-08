# -*- coding: utf-8 -*-
"""Cron/schedule helpers for daily-run morning, intraday, and close jobs."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


MARKER_BEGIN = "# agent-reach daily-run schedule BEGIN"
MARKER_END = "# agent-reach daily-run schedule END"


@dataclass
class CronEntry:
    minute: str
    hour: str
    weekday: str
    job: str
    label: str

    def line(self) -> str:
        return f"{self.minute} {self.hour} * * {self.weekday} {self.job}  # {self.label}"


def _agent_reach_cmd() -> str:
    """Resolve agent-reach executable for crontab."""
    exe = shutil_which("agent-reach")
    if exe:
        return exe
    return f"{sys.executable} -m agent_reach.cli"


def shutil_which(name: str) -> Optional[str]:
    from shutil import which
    return which(name)


def default_entries() -> list[CronEntry]:
    """Default Asia/Shanghai trading schedule (CRON_TZ=Asia/Shanghai)."""
    cmd = _agent_reach_cmd()
    return [
        CronEntry("0", "8", "1-5", f"{cmd} daily-run schedule run morning", "daily-run 早盘 8:00"),
        CronEntry("0,30", "9-14", "1-5", f"{cmd} daily-run schedule run intraday", "daily-run 盘中扫描"),
        CronEntry("30", "15", "1-5", f"{cmd} daily-run schedule run close", "daily-run 收盘 15:30"),
    ]


def render_crontab_block(entries: Optional[list[CronEntry]] = None) -> str:
    entries = entries or default_entries()
    lines = [
        MARKER_BEGIN,
        "CRON_TZ=Asia/Shanghai",
    ]
    for e in entries:
        lines.append(e.line())
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def install_crontab(entries: Optional[list[CronEntry]] = None, *, dry_run: bool = False) -> str:
    """Install or replace agent-reach block in user crontab."""
    block = render_crontab_block(entries)
    if dry_run:
        return block

    crontab_bin = shutil_which("crontab")
    if not crontab_bin:
        fallback = Path.home() / ".agent-reach" / "daily_run" / "crontab.txt"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(block, encoding="utf-8")
        raise RuntimeError(
            f"系统未安装 crontab。已将推荐配置写入 {fallback}，"
            "请手动复制到本地 crontab 或任务计划程序"
        )

    existing = ""
    try:
        existing = subprocess.check_output([crontab_bin, "-l"], stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        existing = ""

    if MARKER_BEGIN in existing:
        before = existing.split(MARKER_BEGIN)[0].rstrip()
        after_parts = existing.split(MARKER_END)
        after = after_parts[1].lstrip("\n") if len(after_parts) > 1 else ""
        new_crontab = before
        if new_crontab:
            new_crontab += "\n"
        new_crontab += block
        if after.strip():
            new_crontab += after
    else:
        new_crontab = existing.rstrip() + "\n\n" + block if existing.strip() else block

    proc = subprocess.run(
        [crontab_bin, "-"],
        input=new_crontab.encode(),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode() or "crontab install failed")
    return new_crontab


def run_scheduled(
    job: str,
    *,
    push: bool = True,
    config=None,
) -> dict:
    """
    Execute a scheduled job: morning | intraday | close.

    Auto-builds snapshot from portfolio config before running workflow.
    """
    from agent_reach.config import Config
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio, save_portfolio
    from agent_reach.daily_run.workflows import load_morning_baseline, run_close, run_morning

    cfg = config or Config()

    # Ensure user portfolio exists
    try:
        load_portfolio()
    except FileNotFoundError:
        from agent_reach.daily_run.snapshot_builder import example_portfolio_path
        save_portfolio(
            __import__("json").loads(example_portfolio_path().read_text(encoding="utf-8"))
        )

    if job == "morning":
        snap, path = build_and_save(report_type="premarket", config=cfg)
        result = run_morning(
            snap,
            push=push,
            start_notify=push,
            config=cfg,
        )
        from agent_reach.daily_run.workflows import save_morning_baseline
        save_morning_baseline(result["snapshot"])
        return {"job": job, "snapshot_path": str(path), "result": result}

    if job == "intraday":
        from agent_reach.daily_run.intraday import run_intraday

        snap, path = build_and_save(report_type="intraday", config=cfg)
        result = run_intraday(
            snap,
            push=push,
            trade=False,
            config=cfg,
        )
        return {"job": job, "snapshot_path": str(path), "result": result}

    if job == "close":
        from agent_reach.daily_run.intraday import load_state

        snap, path = build_and_save(report_type="close", config=cfg)
        # Attach intraday MSS curve if available
        state = load_state()
        if state.scans:
            snap["intraday_scans"] = state.scans
            snap["mss_intraday_actual"] = [s.get("mss_final") for s in state.scans]

        try:
            baseline = load_morning_baseline()
        except FileNotFoundError:
            baseline = snap

        result = run_close(snap, baseline, push=push, config=cfg)
        return {"job": job, "snapshot_path": str(path), "result": result}

    raise ValueError(f"未知定时任务：{job}，可选 morning | intraday | close")
