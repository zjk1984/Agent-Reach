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
    overlay_log_keep_days: int = 90,
    handoff_intraday_keep_days: int = 21,
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

    overlay_cutoff = datetime.now() - timedelta(days=max(7, overlay_log_keep_days))
    overlay_log = base / "overlay_log"
    if overlay_log.exists():
        for path in overlay_log.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime) < overlay_cutoff:
                maybe_delete(path, phase="1", reason=f"overlay_log>{overlay_log_keep_days}d")

    handoff = base / "handoff"
    if handoff.exists() and handoff_intraday_keep_days > 0:
        handoff_cutoff = datetime.now() - timedelta(days=handoff_intraday_keep_days)
        for prefix in ("morning_", "midday_"):
            for path in handoff.glob(f"{prefix}*.json"):
                if path.name.startswith("last_"):
                    continue
                if datetime.fromtimestamp(path.stat().st_mtime) < handoff_cutoff:
                    maybe_delete(path, phase="1", reason=f"handoff_{prefix}>{handoff_intraday_keep_days}d")

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


def run_distill_batches(
    *,
    settings: Optional[dict[str, Any]] = None,
    batch_limit: int = 3000,
    max_rounds: int = 0,
) -> dict[str, Any]:
    """Distill undistilled L0 events in batches until none remain.

    ``max_rounds`` <= 0 means no round cap (process all pending events).
    """
    from agent_reach.daily_run.storage.distill import run_distill

    rounds: list[dict[str, Any]] = []
    total_processed = 0
    total_atoms = 0
    round_num = 0
    while True:
        if max_rounds > 0 and round_num >= max_rounds:
            break
        result = run_distill(limit=max(100, batch_limit), settings=settings)
        if result.get("skipped"):
            return {
                "skipped": True,
                "reason": result.get("reason"),
                "rounds": len(rounds),
                "round_details": rounds,
                "processed_events": total_processed,
                "atoms_created": total_atoms,
                "unlimited": max_rounds <= 0,
            }
        processed = int(result.get("processed_events") or 0)
        rounds.append(result)
        total_processed += processed
        total_atoms += int(result.get("atoms_created") or 0)
        round_num += 1
        if processed <= 0:
            break
    remaining = None
    try:
        from agent_reach.daily_run.storage import get_store

        remaining = get_store(settings).status().get("undistilled_l0")
    except Exception:
        pass
    return {
        "rounds": len(rounds),
        "processed_events": total_processed,
        "atoms_created": total_atoms,
        "remaining_undistilled": remaining,
        "unlimited": max_rounds <= 0,
    }


def prune_database(
    *,
    settings: Optional[dict[str, Any]] = None,
    l0_keep_days: int = 90,
    l1_keep_days: int = 90,
    l0_kinds: Optional[list[str]] = None,
    l1_kinds: Optional[list[str]] = None,
    vacuum: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Drop distilled L0 payloads and stale high-volume L1 atoms."""
    from agent_reach.daily_run.storage import get_store, storage_enabled
    from agent_reach.daily_run.storage.prune_policy import (
        effective_prune_l0_kinds,
        effective_prune_l1_kinds,
    )

    if not storage_enabled(settings):
        return {"skipped": True, "reason": "storage_disabled"}

    store = get_store(settings)
    prune_l0 = getattr(store, "prune_distilled_l0", None)
    if not callable(prune_l0):
        return {"skipped": True, "reason": "backend_no_prune"}

    db_before = getattr(store, "db_file_size_bytes", lambda: 0)()
    cutoff_l0 = _iso_cutoff(l0_keep_days)
    kinds_l0 = l0_kinds if l0_kinds is not None else effective_prune_l0_kinds(settings)
    l0_result = prune_l0(cutoff_iso=cutoff_l0, kinds=kinds_l0, dry_run=dry_run)

    l1_result: dict[str, Any] = {"skipped": True, "reason": "l1_prune_disabled"}
    kinds_l1 = l1_kinds if l1_kinds is not None else effective_prune_l1_kinds(settings)
    prune_l1 = getattr(store, "prune_l1_atoms", None)
    if kinds_l1 and callable(prune_l1):
        cutoff_l1 = _iso_cutoff(l1_keep_days)
        l1_result = prune_l1(cutoff_iso=cutoff_l1, kinds=kinds_l1, dry_run=dry_run)

    vacuum_bytes = 0
    if vacuum and not dry_run:
        vacuum_fn = getattr(store, "vacuum", None)
        if callable(vacuum_fn):
            db_mid = getattr(store, "db_file_size_bytes", lambda: 0)()
            vacuum_fn()
            db_after = getattr(store, "db_file_size_bytes", lambda: 0)()
            vacuum_bytes = max(0, db_mid - db_after)

    db_after = getattr(store, "db_file_size_bytes", lambda: 0)()
    return {
        **l0_result,
        "l1": l1_result,
        "l0_kinds": kinds_l0,
        "l1_kinds": kinds_l1,
        "db_bytes_before": db_before,
        "db_bytes_after": db_after,
        "vacuum_bytes_freed": vacuum_bytes,
    }


def run_prune(
    *,
    settings: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    runs_keep_days: int = 60,
    cache_keep_days: int = 14,
    log_keep_days: int = 30,
    l0_keep_days: int = 90,
    l1_keep_days: int = 90,
    overlay_log_keep_days: int = 90,
    handoff_intraday_keep_days: int = 21,
    vacuum: bool = False,
    dry_run: bool = False,
    distill_first: bool = False,
    distill_batch_limit: int = 3000,
    distill_max_rounds: int = 0,
    repair_quant_first: bool = False,
) -> dict[str, Any]:
    repair_result = None
    if repair_quant_first and not dry_run:
        try:
            from agent_reach.daily_run.quant_repair import repair_quant_chain

            repair_result = repair_quant_chain(settings=settings)
        except Exception as exc:
            repair_result = {"error": str(exc)}

    distill_result = None
    if distill_first:
        distill_result = run_distill_batches(
            settings=settings,
            batch_limit=distill_batch_limit,
            max_rounds=distill_max_rounds,
        )

    files = prune_files(
        root=root,
        runs_keep_days=runs_keep_days,
        cache_keep_days=cache_keep_days,
        log_keep_days=log_keep_days,
        overlay_log_keep_days=overlay_log_keep_days,
        handoff_intraday_keep_days=handoff_intraday_keep_days,
        dry_run=dry_run,
    )
    db = prune_database(
        settings=settings,
        l0_keep_days=l0_keep_days,
        l1_keep_days=l1_keep_days,
        vacuum=vacuum,
        dry_run=dry_run,
    )
    return {
        "repair": repair_result,
        "distill": distill_result,
        "files": files,
        "database": db,
    }


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
        l1_keep_days=int(cfg["l1_keep_days"]),
        overlay_log_keep_days=int(cfg["overlay_log_keep_days"]),
        handoff_intraday_keep_days=int(cfg["handoff_intraday_keep_days"]),
        vacuum=bool(cfg.get("vacuum")),
        dry_run=dry_run,
        distill_first=bool(cfg.get("auto_distill_before_prune")),
        distill_batch_limit=int(cfg["distill_batch_limit"]),
        distill_max_rounds=int(cfg["distill_max_rounds"]),
        repair_quant_first=bool(cfg.get("auto_repair_quant_before_prune")),
    )


def render_prune_markdown(result: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> str:
    from agent_reach.daily_run.storage.config import prune_settings
    from agent_reach.daily_run.storage.prune_policy import PROTECTED_L0_KINDS, PROTECTED_L1_KINDS

    if result.get("skipped"):
        return f"存储清理已跳过：{result.get('reason') or 'disabled'}"

    cfg = prune_settings(settings)
    files = result.get("files") or {}
    db = result.get("database") or {}
    distill = result.get("distill") or {}
    repair = result.get("repair") or {}
    deleted = list(files.get("deleted") or [])

    phase_totals: dict[str, dict[str, float]] = {}
    for item in deleted:
        phase = str(item.get("phase") or "?")
        bucket = phase_totals.setdefault(phase, {"items": 0, "bytes": 0.0})
        bucket["items"] += 1
        bucket["bytes"] += float(item.get("bytes") or 0)

    lines = [
        "## 🧹 周日存储维护",
        "",
        "**安全策略（daily_run.db）**",
        "- **永不删除 L0**：" + "、".join(PROTECTED_L0_KINDS),
        "- **可删 L0**：已蒸馏且超过 "
        f"{cfg['l0_keep_days']} 天的 audit/scan/harness 日志（见配置 prune_l0_kinds）",
        "- **可删 L1**：超过 "
        f"{cfg['l1_keep_days']} 天的 harness 审计 atom（保留 trade/experience/portfolio）",
        "- **L2 场景**（close_handoff、week_open、forecast、trade_case）不在自动清理范围",
        "",
        "**文件保留**",
        f"- runs {cfg['runs_keep_days']}d · cache {cfg['cache_keep_days']}d · overlay_log {cfg['overlay_log_keep_days']}d",
        f"- handoff morning/midday {cfg['handoff_intraday_keep_days']}d（close/week_open 保留）",
        "",
    ]

    if repair and not repair.get("error"):
        wo = (repair.get("week_open") or {})
        handoff = repair.get("close_handoff") or {}
        if handoff.get("repaired") or wo.get("status") == "ok":
            lines.append("**Quant 链路修复**")
            if handoff.get("repaired"):
                lines.append(f"- close seed 补全：{', '.join(handoff['repaired'])}")
            if wo.get("status") == "ok":
                lines.append(f"- week_open：{wo.get('regime')} ({wo.get('week_start')}~{wo.get('week_end')})")
            lines.append("")

    if distill and not distill.get("skipped"):
        unlimited = distill.get("unlimited") is not False and int(cfg.get("distill_max_rounds") or 0) <= 0
        cap_note = "（全量直至清零）" if unlimited else f"（最多 {cfg.get('distill_max_rounds')} 轮）"
        lines.extend(
            [
                "**蒸馏（L0→L1）**",
                f"- 处理 **{distill.get('processed_events', 0)}** 条未蒸馏事件，"
                f"生成 **{distill.get('atoms_created', 0)}** 条 atom {cap_note}",
                f"- 剩余未蒸馏：**{distill.get('remaining_undistilled', '?')}**",
                "",
            ]
        )

    lines.extend(
        [
            "**文件清理**",
            f"- 删除 **{files.get('items', 0)}** 项，释放 **{files.get('mb_freed', 0)} MB**",
        ]
    )
    phase_labels = {
        "0": "Phase 0（bak/缓存/日志）",
        "1": "Phase 1（cache/intraday/overlay/handoff）",
        "2": "Phase 2（runs/）",
    }
    for phase in sorted(phase_totals.keys()):
        bucket = phase_totals[phase]
        label = phase_labels.get(phase, f"Phase {phase}")
        lines.append(f"- {label}：{int(bucket['items'])} 项 · {bucket['bytes'] / 1024 / 1024:.2f} MB")

    lines.extend(["", "**数据库**"])
    before_mb = 0.0
    after_mb = 0.0
    if db.get("skipped"):
        lines.append(f"- 跳过：{db.get('reason') or 'storage_disabled'}")
    else:
        l0_rows = db.get("deleted_rows", db.get("would_delete_rows", 0))
        l0_mb = round((db.get("bytes_estimate") or 0) / 1024 / 1024, 2)
        lines.append(f"- 删除已蒸馏 L0：**{l0_rows}** 行（约 **{l0_mb} MB**）")
        l1 = db.get("l1") or {}
        if not l1.get("skipped"):
            l1_rows = l1.get("deleted_rows", l1.get("would_delete_rows", 0))
            l1_mb = round((l1.get("bytes_estimate") or 0) / 1024 / 1024, 2)
            lines.append(f"- 删除过期 L1 atom：**{l1_rows}** 行（约 **{l1_mb} MB**）")
        before_mb = round(float(db.get("db_bytes_before") or 0) / 1024 / 1024, 1)
        after_mb = round(float(db.get("db_bytes_after") or 0) / 1024 / 1024, 1)
        if before_mb > 0:
            lines.append(f"- daily_run.db：**{before_mb} MB → {after_mb} MB**")
        if db.get("vacuum_bytes_freed"):
            lines.append(f"- VACUUM 释放：**{db['vacuum_bytes_freed'] / 1024 / 1024:.2f} MB**")

    total_mb = float(files.get("mb_freed") or 0)
    if db.get("vacuum_bytes_freed"):
        total_mb += float(db["vacuum_bytes_freed"]) / 1024 / 1024
    if before_mb > 0 and after_mb > 0:
        total_mb += max(0.0, before_mb - after_mb)
    lines.extend(["", f"**合计释放约 {total_mb:.2f} MB**"])

    if deleted:
        lines.extend(["", "**明细（前 8 项）**"])
        for item in deleted[:8]:
            rel = item.get("path") or "?"
            size_mb = float(item.get("bytes") or 0) / 1024 / 1024
            reason = item.get("reason") or ""
            lines.append(f"- `{rel}` · {size_mb:.2f} MB · {reason}")
        if len(deleted) > 8:
            lines.append(f"- … 另有 {len(deleted) - 8} 项")

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
