# -*- coding: utf-8
"""Daily project progress report for fund owner (Feishu @ 20:00 CST)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.job_health import (
    SCHEDULED_OPS_JOBS,
    _load as load_job_health,
    assess_job_health_entry,
    reconcile_stale_job_health,
)
from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai

PROGRESS_JOBS = ("morning", "midday", "intraday", "close")


def _ops_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    raw = settings.get("ops")
    return dict(raw) if isinstance(raw, dict) else {}


def project_progress_feishu_enabled(settings: dict[str, Any]) -> bool:
    block = _ops_cfg(settings).get("project_progress_feishu") or {}
    return block.get("enabled") is True


def _resolve_repo_root() -> Path:
    env = os.environ.get("AGENT_REACH_REPO_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    script = Path(__file__).resolve()
    return script.parents[2]


def resolve_git_head(repo_root: Path) -> dict[str, Any]:
    """Best-effort git HEAD short + branch; never raises."""
    out: dict[str, Any] = {"repo_root": str(repo_root)}
    if not (repo_root / ".git").exists():
        out["error"] = "no .git directory"
        return out
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            out["head_short"] = (r.stdout or "").strip()
        else:
            out["error"] = (r.stderr or r.stdout or "rev-parse failed").strip()[:120]
        br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if br.returncode == 0:
            out["branch"] = (br.stdout or "").strip()
    except OSError as exc:
        out["error"] = str(exc)[:120]
    return out


def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def portfolio_nav_headline(
    portfolio: dict[str, Any],
    *,
    latest_pnl_end_total: Optional[float] = None,
) -> dict[str, Any]:
    cash = portfolio.get("cash")
    total = portfolio.get("total")
    nav = latest_pnl_end_total if latest_pnl_end_total is not None else total
    return {
        "nav": float(nav) if nav is not None else None,
        "cash": float(cash) if cash is not None else None,
        "cash_ratio": portfolio.get("cash_ratio"),
        "nav_source": "pnl_history" if latest_pnl_end_total is not None else "portfolio_config",
    }


def summarize_job_times(job_health: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = (job_health or {}).get("jobs") or {}
    rows: list[dict[str, Any]] = []
    for name in PROGRESS_JOBS:
        entry = jobs.get(name) or {}
        rows.append(
            {
                "job": name,
                "last_success_at": entry.get("last_success_at"),
                "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                "last_error": entry.get("last_error"),
            }
        )
    return rows


def collect_blockers(
    *,
    settings: dict[str, Any],
    job_health: dict[str, Any],
    feishu_configured: bool,
    push_enabled: bool,
) -> list[str]:
    hints: list[str] = []
    if push_enabled and not feishu_configured:
        hints.append("飞书未配置：`feishu_webhook_url` 或 app 凭证缺失，--push 无法送达")
    jobs = (job_health or {}).get("jobs") or {}
    for job in SCHEDULED_OPS_JOBS:
        ok, detail = assess_job_health_entry(job, settings=settings, jobs=jobs)
        if not ok:
            hints.append(f"**{job}** {detail}")
    for row in summarize_job_times(job_health):
        streak = int(row.get("consecutive_failures") or 0)
        if streak > 0 and row["job"] not in SCHEDULED_OPS_JOBS:
            err = (row.get("last_error") or "unknown")[:80]
            hints.append(f"**{row['job']}** 连续失败 {streak} 次 · {err}")
    if not hints:
        hints.append("无（持有人侧 / 调度窗口内）")
    return hints


@dataclass
class ProjectProgressPayload:
    as_of: str
    trading_day: bool
    git: dict[str, Any]
    portfolio: dict[str, Any]
    job_rows: list[dict[str, Any]]
    job_assessments: list[dict[str, Any]]
    blockers: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "trading_day": self.trading_day,
            "git": self.git,
            "portfolio": self.portfolio,
            "job_rows": self.job_rows,
            "job_assessments": self.job_assessments,
            "blockers": self.blockers,
            "generated_at": self.generated_at,
        }


def build_project_progress_payload(
    *,
    settings: dict[str, Any],
    repo_root: Optional[Path] = None,
) -> ProjectProgressPayload:
    from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import load_portfolio

    cfg = settings or load_settings()
    reconcile_stale_job_health(settings=cfg)
    job_health = load_job_health()

    d = today_shanghai()
    td_ok, td_detail = is_trading_day(d, settings=cfg)

    try:
        pf = load_portfolio(settings=cfg)
    except (FileNotFoundError, OSError):
        pf = {}

    pnl_rows = load_daily_pnl_history(settings=cfg)
    latest_nav: Optional[float] = None
    latest_pnl_day = ""
    if pnl_rows:
        last = pnl_rows[-1]
        latest_pnl_day = last.date
        if last.end_total is not None:
            latest_nav = float(last.end_total)

    nav_line = portfolio_nav_headline(pf, latest_pnl_end_total=latest_nav)
    nav_line["latest_pnl_date"] = latest_pnl_day or None

    jobs = (job_health or {}).get("jobs") or {}
    assessments: list[dict[str, Any]] = []
    for job in PROGRESS_JOBS:
        if job in SCHEDULED_OPS_JOBS:
            ok, detail = assess_job_health_entry(job, settings=cfg, jobs=jobs)
            assessments.append({"job": job, "ok": ok, "detail": detail})

    from agent_reach.config import Config
    from agent_reach.integrations.feishu import feishu_mode

    blockers = collect_blockers(
        settings=cfg,
        job_health=job_health,
        feishu_configured=feishu_mode(Config()) is not None,
        push_enabled=project_progress_feishu_enabled(cfg),
    )

    root = repo_root or _resolve_repo_root()
    return ProjectProgressPayload(
        as_of=d.isoformat(),
        trading_day=td_ok,
        git=resolve_git_head(root),
        portfolio=nav_line,
        job_rows=summarize_job_times(job_health),
        job_assessments=assessments,
        blockers=blockers,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def render_project_progress_markdown(payload: ProjectProgressPayload | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, ProjectProgressPayload) else dict(payload)
    lines = [
        f"# 项目进展 · {data.get('as_of')}",
        "",
        "## 运维实况",
        f"- **交易日**：{'是' if data.get('trading_day') else '否'}",
    ]
    pf = data.get("portfolio") or {}
    nav_src = pf.get("nav_source") or "portfolio_config"
    lines.extend(
        [
            f"- **组合 NAV**：{_fmt_money(pf.get('nav'))}（{nav_src}"
            + (f"，收盘日 {pf.get('latest_pnl_date')}" if pf.get("latest_pnl_date") else "")
            + "）",
            f"- **现金**：{_fmt_money(pf.get('cash'))} · 占比 {_fmt_pct(pf.get('cash_ratio'))}",
        ]
    )

    lines.extend(["", "## 代码版本"])
    git = data.get("git") or {}
    if git.get("head_short"):
        branch = git.get("branch") or "?"
        lines.append(f"- **HEAD** `{git['head_short']}` · 分支 `{branch}`")
        lines.append(f"- **仓库** `{git.get('repo_root', '')}`")
    else:
        lines.append(f"- git 不可用：{git.get('error', 'unknown')}")

    lines.extend(["", "## job_health"])
    for row in data.get("job_rows") or []:
        ts = row.get("last_success_at")
        ts_s = str(ts)[:19] if ts else "—"
        streak = int(row.get("consecutive_failures") or 0)
        extra = f" · 连续失败 {streak}" if streak else ""
        lines.append(f"- **{row.get('job')}** 末次成功 {ts_s}{extra}")

    for assess in data.get("job_assessments") or []:
        flag = "OK" if assess.get("ok") else "WARN"
        lines.append(f"  - [{flag}] {assess.get('job')}: {assess.get('detail')}")

    lines.extend(["", "## 阻塞提示"])
    for hint in data.get("blockers") or []:
        lines.append(f"- {hint}")

    lines.append("")
    return "\n".join(lines)


def project_progress_feishu_card(
    payload: ProjectProgressPayload | dict[str, Any],
) -> tuple[str, str, str]:
    data = payload.to_dict() if isinstance(payload, ProjectProgressPayload) else dict(payload)
    blockers = list(data.get("blockers") or [])
    serious = any(
        not a.get("ok")
        for a in (data.get("job_assessments") or [])
    ) or any(
        int(r.get("consecutive_failures") or 0) > 0 for r in (data.get("job_rows") or [])
    )
    if serious and blockers and blockers[0] != "无（持有人侧 / 调度窗口内）":
        tpl = "red"
    elif not serious:
        tpl = "green"
    else:
        tpl = "blue"

    title = f"📋 项目进展 · {data.get('as_of')}"
    pf = data.get("portfolio") or {}
    body_lines = [
        f"**交易日** {'是' if data.get('trading_day') else '否'}",
        f"**NAV** {_fmt_money(pf.get('nav'))} · **现金** {_fmt_money(pf.get('cash'))}",
    ]
    git = data.get("git") or {}
    if git.get("head_short"):
        body_lines.append(f"**代码** `{git['head_short']}` ({git.get('branch') or '?'})")

    body_lines.append("")
    body_lines.append("**调度末次成功**")
    for row in data.get("job_rows") or []:
        ts = row.get("last_success_at")
        ts_s = str(ts)[:16].replace("T", " ") if ts else "—"
        body_lines.append(f"- {row.get('job')}: {ts_s}")

    bad = [a for a in (data.get("job_assessments") or []) if not a.get("ok")]
    if bad:
        body_lines.append("")
        body_lines.append("**job_health**")
        for a in bad[:4]:
            body_lines.append(f"- {a.get('job')}: {(a.get('detail') or '')[:80]}")

    body_lines.append("")
    body_lines.append("**阻塞**")
    for hint in blockers[:5]:
        body_lines.append(f"- {hint.replace('**', '')}")

    body_lines.append("")
    body_lines.append("_20:00 自动进展 · 完整 markdown 见本地 cron 日志_")
    return title, "\n".join(body_lines), tpl


def load_and_build_project_progress(
    *,
    settings: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> ProjectProgressPayload:
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    return build_project_progress_payload(settings=cfg, repo_root=repo_root)