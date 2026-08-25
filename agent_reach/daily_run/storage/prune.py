# -*- coding: utf-8
"""Retention cleanup for daily-run files and SQLite L0 payloads."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _delete_path(path: Path) -> int:
    if not path.exists():
        return 0
    size = _dir_size(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return size


def _iso_cutoff(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    return dt.replace(microsecond=0).isoformat()


def _daily_run_root(root: Optional[Path] = None) -> Path:
    return Path(root or Path.home() / ".agent-reach" / "daily_run").expanduser()


def prune_files(
    *,
    root: Optional[Path] = None,
    runs_keep_days: int = 60,
    cache_keep_days: int = 14,
    log_keep_days: int = 30,
    forecast_keep_days: int = 56,
    market_review_keep_days: int = 30,
    intraday_keep_days: int = 1,
    snapshot_keep: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove stale caches/logs/runs while keeping runtime-critical files."""
    base = _daily_run_root(root)
    today = datetime.now().date().isoformat()
    deleted: list[dict[str, Any]] = []
    bytes_freed = 0

    def maybe_delete(path: Path, *, phase: str, reason: str) -> None:
        nonlocal bytes_freed
        if not path.exists():
            return
        size = _dir_size(path)
        entry = {
            "phase": phase,
            "path": str(path.relative_to(base)),
            "bytes": size,
            "reason": reason,
            "dry_run": dry_run,
        }
        deleted.append(entry)
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        bytes_freed += size

    # Phase 0 — zero risk
    for pattern in ("*.bak*", "*.bak-before-*"):
        for path in base.glob(pattern):
            maybe_delete(path, phase="0", reason="backup")

    intent = base / "intent_cache"
    if intent.exists():
        for path in intent.glob("*.json"):
            if path.name == "rate_window.json":
                continue
            maybe_delete(path, phase="0", reason="intent cache")

    exa = base / "exa_cache"
    if exa.exists():
        for path in exa.glob("*.json"):
            maybe_delete(path, phase="0", reason="exa cache")

    log_cutoff = datetime.now() - timedelta(days=max(1, log_keep_days))
    logs = base / "logs"
    if logs.exists():
        for path in logs.glob("*.log"):
            if datetime.fromtimestamp(path.stat().st_mtime) < log_cutoff:
                maybe_delete(path, phase="0", reason=f"log>{log_keep_days}d")

    weekly = base / "weekly_digest.json"
    if weekly.exists() and datetime.fromtimestamp(weekly.stat().st_mtime) < datetime.now() - timedelta(days=2):
        maybe_delete(weekly, phase="0", reason="stale weekly_digest")

    # Phase 1 — low risk
    cache_cutoff = datetime.now() - timedelta(days=max(1, cache_keep_days))
    cache = base / "cache"
    if cache.exists():
        for path in cache.glob("20*.json"):
            if path.name == f"{today}.json":
                continue
            if datetime.fromtimestamp(path.stat().st_mtime) < cache_cutoff:
                maybe_delete(path, phase="1", reason=f"cache>{cache_keep_days}d")
        for sub in ("kronos", "redfox", "hot_news"):
            subdir = cache / sub
            if not subdir.exists():
                continue
            for path in subdir.glob("*.json"):
                if datetime.fromtimestamp(path.stat().st_mtime) < cache_cutoff:
                    maybe_delete(path, phase="1", reason=f"{sub}>{cache_keep_days}d")

    intraday_cutoff = datetime.now() - timedelta(days=max(0, intraday_keep_days))
    intraday = base / "intraday"
    if intraday.exists():
        for path in intraday.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime) < intraday_cutoff:
                maybe_delete(path, phase="1", reason=f"intraday>{intraday_keep_days}d")

    forecast_cutoff = datetime.now() - timedelta(days=max(1, forecast_keep_days))
    forecasts = base / "forecasts"
    if forecasts.exists():
        for path in forecasts.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime) < forecast_cutoff:
                maybe_delete(path, phase="1", reason=f"forecast>{forecast_keep_days}d")

    market_cutoff = datetime.now() - timedelta(days=max(1, market_review_keep_days))
    market = base / "market_review"
    if market.exists():
        for path in market.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime) < market_cutoff:
                maybe_delete(path, phase="1", reason=f"market_review>{market_review_keep_days}d")

    snap_dir = base / "harness" / "snapshots"
    if snap_dir.exists():
        files = sorted(snap_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[max(3, int(snapshot_keep)) :]:
            maybe_delete(old, phase="1", reason=f"snapshot>keep:{snapshot_keep}")

    # Phase 2 — runs/ day dirs (manifests already in L0 when dual-write enabled)
    runs = base / "runs"
    if runs.exists() and runs_keep_days > 0:
        day_dirs = sorted(
            [p for p in runs.iterdir() if p.is_dir() and len(p.name) >= 10 and p.name[:4].isdigit()],
            key=lambda p: p.name,
        )
        if len(day_dirs) > runs_keep_days:
            for old in day_dirs[: len(day_dirs) - runs_keep_days]:
                maybe_delete(old, phase="2", reason=f"runs>{runs_keep_days}d")

    return {
        "root": str(base),
        "dry_run": dry_run,
        "items": len(deleted),
        "bytes_freed": bytes_freed,
        "mb_freed": round(bytes_freed / 1024 / 1024, 2),
        "deleted": deleted,
    }


def prune_database(
    *,
    settings: Optional[dict[str, Any]] = None,
    l0_keep_days: int = 90,
    l0_kinds: Optional[list[str]] = None,
    vacuum: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Drop distilled L0 payloads older than retention window."""
    from agent_reach.daily_run.storage import get_store, storage_enabled

    if not storage_enabled(settings):
        return {"skipped": True, "reason": "storage_disabled"}

    store = get_store(settings)
    prune_l0 = getattr(store, "prune_distilled_l0", None)
    if not callable(prune_l0):
        return {"skipped": True, "reason": "backend_no_prune"}

    cutoff = _iso_cutoff(l0_keep_days)
    kinds = l0_kinds or [
        "job_run",
        "harness_overlay_diff",
        "harness_memory_diff",
        "harness_audit",
        "harness_refinement",
        "intraday_scan",
        "experience",
        "skill_changelog",
    ]
    result = prune_l0(cutoff_iso=cutoff, kinds=kinds, dry_run=dry_run)

    if vacuum and not dry_run:
        vacuum_fn = getattr(store, "vacuum", None)
        if callable(vacuum_fn):
            before = Path(str(store.status().get("path") or "")).stat().st_size if store.status().get("path") else 0
            vacuum_fn()
            after = Path(str(store.status().get("path") or "")).stat().st_size if store.status().get("path") else 0
            result["vacuum_bytes_freed"] = max(0, before - after)

    return result


def run_prune(
    *,
    settings: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    runs_keep_days: int = 60,
    cache_keep_days: int = 14,
    log_keep_days: int = 30,
    l0_keep_days: int = 90,
    vacuum: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    files = prune_files(
        root=root,
        runs_keep_days=runs_keep_days,
        cache_keep_days=cache_keep_days,
        log_keep_days=log_keep_days,
        dry_run=dry_run,
    )
    db = prune_database(
        settings=settings,
        l0_keep_days=l0_keep_days,
        vacuum=vacuum,
        dry_run=dry_run,
    )
    return {"files": files, "database": db}


def run_scheduled_prune(
    *,
    settings: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run retention cleanup using storage.prune settings."""
    from agent_reach.daily_run.storage.config import prune_settings

    cfg = prune_settings(settings)
    if not cfg.get("enabled", True):
        return {"skipped": True, "reason": "prune_disabled", "settings": cfg}

    return run_prune(
        settings=settings,
        root=root,
        runs_keep_days=int(cfg["runs_keep_days"]),
        cache_keep_days=int(cfg["cache_keep_days"]),
        log_keep_days=int(cfg["log_keep_days"]),
        l0_keep_days=int(cfg["l0_keep_days"]),
        vacuum=bool(cfg.get("vacuum")),
        dry_run=dry_run,
    )


def render_prune_markdown(result: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> str:
    from agent_reach.daily_run.storage.config import prune_settings

    if result.get("skipped"):
        return f"存储清理已跳过：{result.get('reason') or 'disabled'}"

    cfg = prune_settings(settings)
    files = result.get("files") or {}
    db = result.get("database") or {}
    deleted = list(files.get("deleted") or [])

    phase_totals: dict[str, dict[str, float]] = {}
    for item in deleted:
        phase = str(item.get("phase") or "?")
        bucket = phase_totals.setdefault(phase, {"items": 0, "bytes": 0.0})
        bucket["items"] += 1
        bucket["bytes"] += float(item.get("bytes") or 0)

    lines = [
        "**周日存储维护完成**",
        "",
        "**保留策略**",
        f"- runs manifest：{cfg['runs_keep_days']} 天",
        f"- 日缓存 / 子缓存：{cfg['cache_keep_days']} 天",
        f"- cron 日志：{cfg['log_keep_days']} 天",
        f"- 已蒸馏 L0：{cfg['l0_keep_days']} 天",
        "",
        "**文件清理**",
        f"- 删除 **{files.get('items', 0)}** 项，释放 **{files.get('mb_freed', 0)} MB**",
    ]
    phase_labels = {"0": "Phase 0（bak/缓存/日志）", "1": "Phase 1（cache/intraday/forecast）", "2": "Phase 2（runs/）"}
    for phase in sorted(phase_totals.keys()):
        bucket = phase_totals[phase]
        label = phase_labels.get(phase, f"Phase {phase}")
        lines.append(f"- {label}：{int(bucket['items'])} 项 · {bucket['bytes'] / 1024 / 1024:.2f} MB")

    lines.extend(["", "**数据库**"])
    if db.get("skipped"):
        lines.append(f"- 跳过：{db.get('reason') or 'storage_disabled'}")
    else:
        rows = db.get("deleted_rows", db.get("would_delete_rows", 0))
        mb = round((db.get("bytes_estimate") or 0) / 1024 / 1024, 2)
        lines.append(f"- 删除已蒸馏 L0：**{rows}** 行（约 **{mb} MB**）")
        if db.get("vacuum_bytes_freed") is not None:
            lines.append(f"- VACUUM 释放：**{db['vacuum_bytes_freed'] / 1024 / 1024:.2f} MB**")

    total_mb = float(files.get("mb_freed") or 0)
    if db.get("vacuum_bytes_freed"):
        total_mb += float(db["vacuum_bytes_freed"]) / 1024 / 1024
    lines.extend(["", f"**合计释放约 {total_mb:.2f} MB**"])

    if deleted:
        lines.extend(["", "**明细（前 10 项）**"])
        for item in deleted[:10]:
            rel = item.get("path") or "?"
            size_mb = float(item.get("bytes") or 0) / 1024 / 1024
            reason = item.get("reason") or ""
            lines.append(f"- `{rel}` · {size_mb:.2f} MB · {reason}")
        if len(deleted) > 10:
            lines.append(f"- … 另有 {len(deleted) - 10} 项")

    return "\n".join(lines)


def push_prune_result_card(
    result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
    title: str = "🧹 存储清理 · 周日维护",
) -> Optional[dict[str, Any]]:
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import send_card

    if result.get("skipped"):
        return None

    markdown = render_prune_markdown(result, settings=settings)
    files = result.get("files") or {}
    db = result.get("database") or {}
    total_freed = float(files.get("bytes_freed") or 0)
    if db.get("vacuum_bytes_freed"):
        total_freed += float(db["vacuum_bytes_freed"])
    template = "green" if total_freed > 0 else "blue"
    cfg_obj = config or Config()
    report_cfg = (settings or {}).get("report") or {}
    template = report_cfg.get("feishu_template_storage_prune", template)
    return send_card(cfg_obj, title, markdown, template=template)
