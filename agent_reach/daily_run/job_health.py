# -*- coding: utf-8
"""Track scheduled job outcomes and alert on consecutive failures."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import (
    shanghai_date_of_iso,
    today_shanghai,
    trading_day_before,
    trading_day_on_or_before,
)

SCHEDULED_OPS_JOBS = ("close", "morning", "intraday")
PRECHECK_HEALTH_JOBS = ("close", "morning")


def health_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "job_health.json"


def _load() -> dict[str, Any]:
    p = health_path()
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_job_health

        if storage_db_reads_allowed(None, file_path=p):
            from agent_reach.daily_run.settings import load_settings

            db_data = read_job_health(settings=load_settings())
            if isinstance(db_data, dict) and db_data.get("jobs") is not None:
                return db_data
    except Exception:
        pass
    if not p.exists():
        return {"jobs": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"jobs": {}}
    if not isinstance(data, dict):
        return {"jobs": {}}
    data.setdefault("jobs", {})
    return data


def _save(data: dict[str, Any]) -> None:
    p = health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ops_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    raw = settings.get("ops")
    return dict(raw) if isinstance(raw, dict) else {}


def feishu_ops_notify_enabled(settings: dict[str, Any], config=None) -> bool:
    """True when ops wants Feishu alerts and credentials are present."""
    if _ops_cfg(settings).get("push_job_health_fail", True) is False:
        return False
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import feishu_mode

    cfg = config or Config()
    return feishu_mode(cfg) is not None


def acceptable_success_dates(settings: dict[str, Any]) -> set[date]:
    today = today_shanghai()
    prev_td = trading_day_before(today, 1, settings=settings)
    return {today, prev_td}


def job_last_success_date(job: str, jobs: dict[str, Any]) -> Optional[date]:
    entry = jobs.get(job) or {}
    raw = entry.get("last_success_at")
    if not raw:
        return None
    return shanghai_date_of_iso(str(raw))


def job_last_success_trading_day(
    job: str,
    jobs: dict[str, Any],
    *,
    settings: dict[str, Any],
) -> Optional[date]:
    last_d = job_last_success_date(job, jobs)
    if last_d is None:
        return None
    return trading_day_on_or_before(last_d, settings=settings)


def reconcile_stale_job_health(*, settings: dict[str, Any]) -> bool:
    """Persist consecutive_failures=0 when last_success is still within the trading window."""
    data = _load()
    jobs = dict(data.get("jobs") or {})
    acceptable = acceptable_success_dates(settings)
    changed = False

    for job in SCHEDULED_OPS_JOBS:
        entry = dict(jobs.get(job) or {})
        streak = int(entry.get("consecutive_failures") or 0)
        if streak <= 0:
            continue
        last_td = job_last_success_trading_day(job, {job: entry}, settings=settings)
        if last_td is not None and last_td in acceptable:
            entry["consecutive_failures"] = 0
            entry["last_error"] = None
            jobs[job] = entry
            changed = True

    if not changed:
        return False

    data["jobs"] = jobs
    _save(data)
    try:
        from agent_reach.daily_run.storage.hooks import on_l1_state

        on_l1_state("job_health", "job_health", data)
    except Exception:
        pass
    return True


def assess_job_health_entry(
    job: str,
    *,
    settings: dict[str, Any],
    jobs: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return (ok, detail) for one scheduled job vs trading-day expectations."""
    jobs_map = jobs if jobs is not None else (_load().get("jobs") or {})
    acceptable = acceptable_success_dates(settings)
    prev_td = min(acceptable) if len(acceptable) == 2 else today_shanghai()
    today = max(acceptable) if len(acceptable) == 2 else today_shanghai()

    entry = jobs_map.get(job) or {}
    streak = int(entry.get("consecutive_failures") or 0)
    last_d = job_last_success_date(job, jobs_map)
    last_td = job_last_success_trading_day(job, jobs_map, settings=settings)

    if streak > 0 and last_td is not None and last_td in acceptable:
        streak = 0

    if streak > 0:
        err = (entry.get("last_error") or "unknown")[:120]
        return False, f"连续失败 {streak} 次 · {err}"

    if last_td is None:
        return False, "无 last_success_at 记录"

    if last_td not in acceptable:
        wall = last_d.isoformat() if last_d else "?"
        return (
            False,
            f"末次成功 {wall}（交易日 {last_td.isoformat()}），"
            f"期望 {prev_td} 或 {today}（交易日）",
        )

    wall = last_d.isoformat() if last_d else last_td.isoformat()
    return True, f"末次成功 {wall}"


def record_job_outcome(
    job: str,
    *,
    success: bool,
    error: Optional[str] = None,
) -> int:
    """Record success/failure; return consecutive failure count after this run."""
    data = _load()
    jobs = data["jobs"]
    entry = jobs.get(job) or {"consecutive_failures": 0, "last_success_at": None, "last_error": None}
    now = datetime.now(timezone.utc).isoformat()

    if success:
        entry["consecutive_failures"] = 0
        entry["last_success_at"] = now
        entry["last_error"] = None
    else:
        entry["consecutive_failures"] = int(entry.get("consecutive_failures") or 0) + 1
        entry["last_failure_at"] = now
        entry["last_error"] = (error or "unknown")[:500]

    jobs[job] = entry
    _save(data)
    try:
        from agent_reach.daily_run.storage.hooks import on_l1_state

        on_l1_state("job_health", "job_health", data)
    except Exception:
        pass
    return 0 if success else int(entry["consecutive_failures"])


def notify_scheduled_job_failure(
    job: str,
    *,
    error: str,
    streak: int,
    settings: dict[str, Any],
    config=None,
    heal_hint: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Feishu FAIL card on scheduled job failure (graceful skip if Feishu unavailable)."""
    if job not in SCHEDULED_OPS_JOBS:
        return None
    if not feishu_ops_notify_enabled(settings, config):
        return {"skipped": True, "reason": "feishu_unconfigured_or_disabled"}

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg = config or Config()
    title = f"❌ daily-run FAIL · {job}"
    body_lines = [
        f"任务 **{job}** 运行失败（连续失败 **{streak}** 次）。",
        "",
        f"**错误：** {(error or 'unknown')[:400]}",
    ]
    ok, stale_detail = assess_job_health_entry(job, settings=settings)
    if not ok:
        body_lines.extend(["", f"**job_health：** {stale_detail}"])
    if heal_hint:
        body_lines.extend(["", f"**自愈：** {heal_hint}"])
    body_lines.extend(
        [
            "",
            "请检查 cron 日志：`~/.agent-reach/daily_run/logs/`",
            "补跑：`python3 -m agent_reach.cli daily-run schedule run "
            + job
            + "`",
        ]
    )
    try:
        return send_card(
            cfg,
            title,
            "\n".join(body_lines),
            template="red",
        )
    except FeishuError:
        return {"skipped": True, "reason": "feishu_error"}


def notify_job_health_stale(
    job: str,
    *,
    detail: str,
    settings: dict[str, Any],
    config=None,
) -> Optional[dict[str, Any]]:
    """Feishu when last_success is missing/stale (no fresh run failure)."""
    if not feishu_ops_notify_enabled(settings, config):
        return {"skipped": True, "reason": "feishu_unconfigured_or_disabled"}

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg = config or Config()
    title = f"❌ job_health FAIL · {job}"
    body = (
        f"任务 **{job}** 未满足交易日成功窗口。\n\n"
        f"**详情：** {detail}\n\n"
        "建议补跑对应 `daily-run schedule run` 或检查 cron。"
    )
    try:
        return send_card(cfg, title, body, template="red")
    except FeishuError:
        return {"skipped": True, "reason": "feishu_error"}


def notify_ops_precheck_fail(
    summary: str,
    *,
    settings: dict[str, Any],
    config=None,
) -> Optional[dict[str, Any]]:
    if not feishu_ops_notify_enabled(settings, config):
        return {"skipped": True, "reason": "feishu_unconfigured_or_disabled"}

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg = config or Config()
    title = "❌ ops 交易日预检 FAIL"
    body = summary + "\n\n（自动推送 · ops-trading-day-precheck）"
    try:
        return send_card(cfg, title, body, template="red")
    except FeishuError:
        return {"skipped": True, "reason": "feishu_error"}


def close_has_resumable_checkpoint(*, day: Optional[str] = None) -> bool:
    from agent_reach.daily_run.job_checkpoint import checkpoint_path, list_done_steps, load_checkpoint

    path = checkpoint_path("close", day)
    if not path.exists():
        return False
    data = load_checkpoint("close", day)
    steps = data.get("steps") or {}
    if not steps:
        return False
    done = list_done_steps("close", day)
    return len(done) < len(steps)


def attempt_auto_resume_close(
    *,
    settings: dict[str, Any],
    config=None,
    push: bool = True,
) -> dict[str, Any]:
    """Run close again when today's checkpoint indicates a partial run."""
    ops = _ops_cfg(settings)
    if ops.get("auto_resume_close", True) is False:
        return {"skipped": True, "reason": "auto_resume_close_disabled"}

    if not close_has_resumable_checkpoint():
        return {"skipped": True, "reason": "no_resumable_checkpoint"}

    from loguru import logger

    from agent_reach.daily_run.schedule import run_scheduled

    logger.warning("ops auto_resume_close: resuming close from checkpoint")
    try:
        result = run_scheduled("close", push=push, config=config, auto_heal=False)
        return {"resumed": True, "result": result}
    except Exception as exc:
        return {"resumed": False, "error": str(exc)[:500]}


def maybe_alert_consecutive_failures(
    job: str,
    *,
    settings: dict[str, Any],
    config=None,
) -> Optional[dict[str, Any]]:
    """Send Feishu alert when consecutive failures reach threshold."""
    sched = settings.get("schedule") or {}
    threshold = int(sched.get("alert_after_consecutive_failures", 3))
    if threshold <= 0:
        return None

    data = _load()
    entry = (data.get("jobs") or {}).get(job) or {}
    streak = int(entry.get("consecutive_failures") or 0)
    if streak < threshold:
        return None

    last_err = entry.get("last_error") or "未知错误"
    return notify_scheduled_job_failure(
        job,
        error=last_err,
        streak=streak,
        settings=settings,
        config=config,
        heal_hint=f"已连续 {streak} 次失败（阈值 {threshold}），请优先处理。",
    )
