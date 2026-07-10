# -*- coding: utf-8
"""Cron/schedule helpers for daily-run morning, intraday, and close jobs."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent_reach.daily_run.run_manifest import StepTimer, save_run_manifest


MARKER_BEGIN = "# agent-reach daily-run schedule BEGIN"
MARKER_END = "# agent-reach daily-run schedule END"

# 11 timed intraday slots: 7:00 盘前 + 9:30–15:00 盘中；8:00 全量早盘由 morning 任务记录 S2
INTRADAY_SCAN_TIMES: list[tuple[str, str]] = [
    ("0", "7"),
    ("30", "9"),
    ("0", "10"),
    ("30", "10"),
    ("0", "11"),
    ("30", "11"),
    ("0", "13"),
    ("30", "13"),
    ("0", "14"),
    ("30", "14"),
    ("0", "15"),
]


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
    exe = shutil_which("agent-reach")
    if exe:
        return exe
    return f"{sys.executable} -m agent_reach.cli"


def shutil_which(name: str) -> Optional[str]:
    from shutil import which
    return which(name)


def default_entries() -> list[CronEntry]:
    """Default 北京时间 trading schedule (CRON_TZ=Asia/Shanghai)."""
    cmd = _agent_reach_cmd()
    entries = [
        CronEntry("0", "8", "1-5", f"{cmd} daily-run schedule run morning", "daily-run 早盘全量 8:00"),
    ]
    for i, (minute, hour) in enumerate(INTRADAY_SCAN_TIMES, start=1):
        scan_num = i if i == 1 else i + 1  # S1 @7:00; S3+ @9:30 (S2 @8:00 morning)
        label = f"daily-run 盘前 S{scan_num}/12" if i == 1 else f"daily-run 盘中 S{scan_num}/12"
        entries.append(
            CronEntry(
                minute,
                hour,
                "1-5",
                f"{cmd} daily-run schedule run intraday",
                label,
            )
        )
    entries.append(
        CronEntry("30", "15", "1-5", f"{cmd} daily-run schedule run close", "daily-run 收盘 15:30")
    )
    entries.append(
        CronEntry("0", "9", "6", f"{cmd} daily-run schedule run weekly", "daily-run 周报 周六 9:00")
    )
    entries.append(
        CronEntry("0", "9", "0", f"{cmd} daily-run schedule run forecast", "daily-run 下周预测 周日 9:00")
    )
    return entries


def render_crontab_block(entries: Optional[list[CronEntry]] = None) -> str:
    entries = entries or default_entries()
    lines = [MARKER_BEGIN, "CRON_TZ=Asia/Shanghai"]
    for e in entries:
        lines.append(e.line())
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def install_crontab(entries: Optional[list[CronEntry]] = None, *, dry_run: bool = False) -> str:
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


def _doctor_channels(config) -> dict:
    from agent_reach.doctor import check_all

    return check_all(config)


def run_scheduled(
    job: str,
    *,
    push: bool = True,
    config=None,
) -> dict:
    """Execute morning | intraday | close | weekly with auto snapshot + doctor + manifest."""
    from agent_reach.config import Config
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio, save_portfolio
    from agent_reach.daily_run.workflows import load_morning_baseline, run_close, run_forecast, run_morning, run_weekly

    cfg_obj = config or Config()
    settings = load_settings()
    t0 = time.perf_counter()

    from agent_reach.daily_run.trade_calendar import is_trading_day

    if job not in ("weekly", "forecast"):
        trading_ok, trading_reason = is_trading_day(settings=settings)
        if not trading_ok:
            result = {"job": job, "skipped": True, "reason": trading_reason}
            save_run_manifest(job, result, duration_ms=0)
            return result

    doctor = _doctor_channels(cfg_obj) if job not in ("weekly", "forecast") else {}

    try:
        load_portfolio()
    except FileNotFoundError:
        from agent_reach.daily_run.snapshot_builder import example_portfolio_path

        save_portfolio(
            __import__("json").loads(example_portfolio_path().read_text(encoding="utf-8"))
        )

    result: dict
    feishu = None

    if job == "morning":
        from agent_reach.daily_run.intraday import load_state, record_scan_from_evaluation
        from agent_reach.daily_run.pipeline import evaluate_snapshot
        from agent_reach.daily_run.portfolio_manager import increment_holding_days, is_auto_adjust_enabled
        from agent_reach.daily_run.watchlist_manager import adjust_watchlist, is_watchlist_adjust_enabled

        with StepTimer("schedule.morning"):
            if is_auto_adjust_enabled(settings):
                pf = load_portfolio()
                save_portfolio(increment_holding_days(pf))

            snap, path = build_and_save(
                report_type="premarket",
                config=cfg_obj,
                settings=settings,
            )

            # 07:00 cron 未跑时（fork 仓库常见）：用盘前 snapshot 补 S1，08:00 全量仍为 S2
            s1_backfill = None
            state = load_state()
            if not state.scans:
                pre_eval = evaluate_snapshot(snap, settings, doctor_channels=doctor)
                s1_backfill = record_scan_from_evaluation(
                    snap,
                    pre_eval,
                    settings=settings,
                    source="premarket",
                )

            run_result = run_morning(
                snap,
                settings=settings,
                doctor_channels=doctor,
                push=push,
                start_notify=push,
                config=cfg_obj,
            )
            from agent_reach.daily_run.workflows import save_morning_baseline

            save_morning_baseline(run_result["snapshot"])
            scan_result = record_scan_from_evaluation(
                run_result["snapshot"],
                run_result["evaluation"],
                settings=settings,
                source="morning",
            )
            run_result["steps"].append("scan_s2")
            run_result["scan"] = scan_result
            if s1_backfill is not None:
                run_result["s1_backfill"] = s1_backfill
                run_result["steps"].append("scan_s1_backfill")

            wl_result = None
            if is_watchlist_adjust_enabled(settings):
                pf = load_portfolio()
                wl_result = adjust_watchlist(
                    pf,
                    run_result["snapshot"],
                    settings,
                    "morning",
                )
                if wl_result.applied:
                    save_portfolio(wl_result.portfolio)
                run_result["watchlist_adjust"] = wl_result.to_dict()

            result = {"job": job, "snapshot_path": str(path), "result": run_result}
            feishu = run_result.get("feishu")

    elif job == "intraday":
        from agent_reach.daily_run.intraday import MAX_SCANS, load_state, run_intraday, should_evaluate_trade

        with StepTimer("schedule.intraday"):
            state = load_state()
            if len(state.scans) >= MAX_SCANS:
                result = {
                    "job": job,
                    "skipped": True,
                    "reason": f"今日扫描已达 {MAX_SCANS} 次上限",
                }
            else:
                snap, path = build_and_save(
                    report_type="intraday",
                    config=cfg_obj,
                    settings=settings,
                )
                do_trade = should_evaluate_trade(state, settings)
                run_result = run_intraday(
                    snap,
                    settings=settings,
                    doctor_channels=doctor,
                    push=push,
                    trade=do_trade,
                    config=cfg_obj,
                )
                result = {
                    "job": job,
                    "snapshot_path": str(path),
                    "trade_evaluated": do_trade,
                    "result": run_result,
                }
                feishu = run_result.get("feishu")

    elif job == "close":
        from agent_reach.daily_run.intraday import load_state

        with StepTimer("schedule.close"):
            pf = load_portfolio()
            snap, path = build_and_save(
                report_type="close",
                config=cfg_obj,
                settings=settings,
                portfolio=pf,
            )
            state = load_state()
            if state.scans:
                snap["intraday_scans"] = state.scans
                snap["mss_intraday_actual"] = [s.get("mss_final") for s in state.scans]

            try:
                baseline = load_morning_baseline()
            except FileNotFoundError as exc:
                if push:
                    from agent_reach.integrations.feishu import send_card

                    send_card(
                        cfg_obj,
                        "⚠️ 收盘复盘缺少早盘基线",
                        f"未找到 `last_morning.json`：{exc}\n\n请先运行 `daily-run morning --save-baseline`",
                        template="red",
                    )
                raise

            from agent_reach.daily_run.workflows import prepare_close_run

            prepared = prepare_close_run(
                snap,
                baseline,
                pf,
                settings=settings,
                scans=state.scans,
                trades=state.trades,
                attach_intraday=False,
            )
            snap = prepared["snapshot"]
            wl_result_dict = prepared["watchlist_adjust"]
            code_review_dict = prepared["code_review"]

            run_result = run_close(
                snap,
                baseline,
                settings=settings,
                push=push,
                config=cfg_obj,
                intraday_scans=state.scans,
                intraday_trades=state.trades,
                watchlist_adjust=wl_result_dict,
                code_review=code_review_dict,
            )
            run_result["code_review"] = code_review_dict
            run_result["prepare_steps"] = prepared["steps"]
            if wl_result_dict is not None:
                run_result["watchlist_adjust"] = wl_result_dict

            result = {"job": job, "snapshot_path": str(path), "result": run_result}
            feishu = run_result.get("feishu")

    elif job == "weekly":
        with StepTimer("schedule.weekly"):
            pf = load_portfolio()
            snap, path = build_and_save(
                report_type="close",
                config=cfg_obj,
                settings=settings,
                portfolio=pf,
            )
            run_result = run_weekly(
                snap,
                settings=settings,
                push=push,
                config=cfg_obj,
                portfolio=pf,
            )
            result = {"job": job, "snapshot_path": str(path), "result": run_result}
            feishu = run_result.get("feishu")

    elif job == "forecast":
        with StepTimer("schedule.forecast"):
            pf = load_portfolio()
            snap, path = build_and_save(
                report_type="close",
                config=cfg_obj,
                settings=settings,
                portfolio=pf,
            )
            run_result = run_forecast(
                snap,
                settings=settings,
                push=push,
                config=cfg_obj,
                portfolio=pf,
            )
            result = {
                "job": job,
                "snapshot_path": str(path),
                "forecast_path": run_result.get("forecast_path"),
                "result": run_result,
            }
            feishu = run_result.get("feishu")
    else:
        raise ValueError(f"未知定时任务：{job}，可选 morning | intraday | close | weekly | forecast")

    duration_ms = (time.perf_counter() - t0) * 1000
    manifest_path = save_run_manifest(job, result, feishu=feishu, duration_ms=duration_ms)
    result["manifest_path"] = str(manifest_path)
    return result
