# -*- coding: utf-8
"""Track scheduled job outcomes and alert on consecutive failures."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def health_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "job_health.json"


def _load() -> dict[str, Any]:
    p = health_path()
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
    return 0 if success else int(entry["consecutive_failures"])


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

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg = config or Config()
    last_err = entry.get("last_error") or "未知错误"
    title = f"⚠️ daily-run 连续失败 · {job}"
    body = (
        f"任务 **{job}** 已连续失败 **{streak}** 次（阈值 {threshold}）。\n\n"
        f"**最近错误：** {last_err}\n\n"
        "请检查 cron 日志、飞书凭证与行情数据源。"
    )
    try:
        return send_card(cfg, title, body, template="red")
    except FeishuError:
        return None
