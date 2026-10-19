# -*- coding: utf-8
"""Trading-day ops precheck (git, job_health, doctor smoke, disk)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from agent_reach.daily_run.job_health import _load as load_job_health
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai

# Channels / integrations that must not be hard-failed before the open.
_DOCTOR_CRITICAL_CHANNELS = frozenset({"xueqiu", "web", "rss"})
_DOCTOR_WARN_CHANNELS = frozenset({"xueqiu"})


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    severity: str = "fail"  # fail | warn | info


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def check_git_main_sync(repo_root: Path, *, fetch: bool = True) -> CheckResult:
    branch = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        return CheckResult("git", False, f"当前分支 {branch!r}，生产应跟踪 main")

    dirty = _run_git(repo_root, "status", "--porcelain").stdout.strip()
    if dirty:
        return CheckResult("git", False, "工作区有未提交改动")

    if fetch:
        fetch_r = _run_git(repo_root, "fetch", "origin", "main")
        if fetch_r.returncode != 0:
            err = (fetch_r.stderr or fetch_r.stdout or "fetch failed").strip()[:200]
            return CheckResult("git", False, f"无法 fetch origin/main：{err}")

    local = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    remote = _run_git(repo_root, "rev-parse", "origin/main").stdout.strip()
    if not local or not remote:
        return CheckResult("git", False, "无法解析 HEAD 或 origin/main")

    if local != remote:
        behind = _run_git(repo_root, "rev-list", "--count", f"HEAD..origin/main").stdout.strip()
        ahead = _run_git(repo_root, "rev-list", "--count", f"origin/main..HEAD").stdout.strip()
        if behind and behind != "0":
            return CheckResult(
                "git",
                False,
                f"落后 origin/main {behind} 个提交（请 git pull）",
            )
        if ahead and ahead != "0":
            return CheckResult(
                "git",
                True,
                f"与 origin/main 一致或仅本地超前 {ahead} 提交",
                severity="warn",
            )
        return CheckResult("git", False, "与 origin/main 分叉，需人工对齐")

    short = local[:8]
    return CheckResult("git", True, f"main @ {short} = origin/main")


def check_pip_editable(repo_root: Path) -> CheckResult:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show", "agent-reach"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return CheckResult("pip", False, f"pip 不可用：{exc}")

    if proc.returncode != 0:
        return CheckResult(
            "pip",
            False,
            "未安装 agent-reach；请 pip install -c constraints.txt -e '.[dev]'",
        )

    editable: Optional[str] = None
    for line in proc.stdout.splitlines():
        if line.startswith("Editable project location:"):
            editable = line.split(":", 1)[1].strip()
            break

    if not editable:
        return CheckResult(
            "pip",
            False,
            "agent-reach 非 editable 安装；请 pip install -e '.[dev]'",
        )

    try:
        same = Path(editable).resolve() == repo_root.resolve()
    except OSError:
        same = False

    if not same:
        return CheckResult(
            "pip",
            False,
            f"editable 路径 {editable} 与仓库 {repo_root} 不一致",
        )

    return CheckResult("pip", True, f"editable @ {editable}")


def check_job_health(*, settings: Optional[dict] = None) -> list[CheckResult]:
    from agent_reach.daily_run.job_health import (
        PRECHECK_HEALTH_JOBS,
        assess_job_health_entry,
        attempt_auto_resume_close,
        close_has_resumable_checkpoint,
        reconcile_stale_job_health,
    )

    settings = settings or load_settings()
    reconcile_stale_job_health(settings=settings)
    data = load_job_health()
    jobs = data.get("jobs") or {}
    results: list[CheckResult] = []

    for job in PRECHECK_HEALTH_JOBS:
        ok, detail = assess_job_health_entry(job, settings=settings, jobs=jobs)
        if (
            not ok
            and job == "close"
            and close_has_resumable_checkpoint()
            and (settings.get("ops") or {}).get("auto_resume_close", True) is not False
        ):
            heal = attempt_auto_resume_close(settings=settings, push=False)
            if heal.get("resumed"):
                reconcile_stale_job_health(settings=settings)
                data = load_job_health()
                jobs = data.get("jobs") or {}
                ok, detail = assess_job_health_entry(job, settings=settings, jobs=jobs)
                if ok:
                    detail = f"{detail}（已 auto_resume_close 续跑）"
        results.append(CheckResult(f"job_health:{job}", ok, detail))

    return results


def check_doctor_smoke(*, skip: bool = False) -> CheckResult:
    if skip:
        return CheckResult("doctor", True, "已跳过 (OPS_PRECHECK_SKIP_DOCTOR=1)", severity="info")

    from agent_reach.config import Config
    from agent_reach.doctor import check_all, check_integrations

    config = Config()
    channels = check_all(config)
    integrations = check_integrations(config)

    hard_fail: list[str] = []
    warns: list[str] = []

    for key, row in channels.items():
        status = row.get("status")
        name = row.get("name") or key
        if key in _DOCTOR_CRITICAL_CHANNELS and status == "error":
            hard_fail.append(f"{name} ({key})")
        elif key in _DOCTOR_WARN_CHANNELS and status == "warn":
            warns.append(f"{name} ({key}): {row.get('message', '')[:80]}")

    feishu = integrations.get("feishu") or {}
    if feishu.get("status") == "error":
        hard_fail.append("飞书推送")

    if hard_fail:
        return CheckResult("doctor", False, "异常：" + "；".join(hard_fail))

    if warns:
        return CheckResult(
            "doctor",
            True,
            "通过（警告：" + "；".join(warns) + "）",
            severity="warn",
        )

    return CheckResult("doctor", True, "关键通道 smoke 通过")


def check_disk_space(min_gb: float = 10.0, path: Optional[Path] = None) -> CheckResult:
    target = path or Path.home()
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    if free_gb < min_gb:
        return CheckResult(
            "disk",
            False,
            f"{target} 可用 {free_gb:.1f}GB < {min_gb}GB",
        )
    return CheckResult("disk", True, f"{target} 可用 {free_gb:.1f}GB")


def check_worker_note() -> CheckResult:
    """Optional: Cursor private worker — informational only."""
    cursor = shutil.which("cursor")
    if not cursor:
        return CheckResult(
            "worker",
            True,
            "未检测到 cursor CLI（Worker 状态未检）",
            severity="info",
        )

    proc = subprocess.run(
        ["pgrep", "-af", "cursor"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [ln for ln in (proc.stdout or "").splitlines() if "worker" in ln.lower()]
    if lines:
        return CheckResult(
            "worker",
            True,
            f"疑似 Worker 进程 {len(lines)} 条（pgrep cursor）",
            severity="info",
        )
    return CheckResult(
        "worker",
        True,
        "cursor CLI 在 PATH，但未发现 worker 进程（请确认 systemd/常开）",
        severity="info",
    )


def run_precheck(
    repo_root: Path,
    *,
    fetch_git: bool = True,
    skip_doctor: bool = False,
    skip_non_trading: bool = True,
    settings: Optional[dict] = None,
) -> tuple[list[CheckResult], int]:
    settings = settings or load_settings()
    today = today_shanghai()
    trading, reason = is_trading_day(today, settings=settings)

    results: list[CheckResult] = [
        CheckResult(
            "calendar",
            True,
            f"{today.isoformat()} {'交易日' if trading else '非交易日'} ({reason})",
            severity="info",
        )
    ]

    if skip_non_trading and not trading:
        return results, 0

    results.append(check_git_main_sync(repo_root, fetch=fetch_git))
    results.append(check_pip_editable(repo_root))
    results.extend(check_job_health(settings=settings))
    results.append(check_doctor_smoke(skip=skip_doctor))
    results.append(check_disk_space())
    results.append(check_worker_note())

    failed = [r for r in results if not r.ok and r.severity == "fail"]
    exit_code = 1 if failed else 0
    return results, exit_code


def format_summary(results: list[CheckResult], *, exit_code: int) -> str:
    lines = ["=== ops-trading-day-precheck ==="]
    for r in results:
        if r.ok:
            mark = "OK" if r.severity == "fail" else r.severity.upper()
        else:
            mark = "FAIL"
        lines.append(f"[{mark}] {r.name}: {r.detail}")
    verdict = "PASS" if exit_code == 0 else "FAIL"
    lines.append(f"--- {verdict} (exit {exit_code}) ---")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Trading-day ops precheck")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-fetch", action="store_true", help="Skip git fetch")
    parser.add_argument(
        "--force-non-trading",
        action="store_true",
        help="Run all checks even on non-trading days",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parents[2]
    repo_root = Path(os.environ.get("AGENT_REACH_REPO_ROOT", script_dir))
    skip_doctor = os.environ.get("OPS_PRECHECK_SKIP_DOCTOR", "").strip() in ("1", "true", "yes")

    results, exit_code = run_precheck(
        repo_root,
        fetch_git=not args.no_fetch,
        skip_doctor=skip_doctor,
        skip_non_trading=not args.force_non_trading,
    )

    summary = format_summary(results, exit_code=exit_code)

    if args.json:
        payload = {
            "exit_code": exit_code,
            "checks": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "detail": r.detail,
                    "severity": r.severity,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(summary)

    if exit_code != 0:
        from agent_reach.config import Config
        from agent_reach.daily_run.job_health import notify_ops_precheck_fail
        from agent_reach.daily_run.settings import load_settings

        notify_ops_precheck_fail(summary, settings=load_settings(), config=Config())

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
