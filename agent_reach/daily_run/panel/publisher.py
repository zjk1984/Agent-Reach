# -*- coding: utf-8 -*-
"""Static HTML report publisher and GitHub archive manager.

After every scheduled cron job execution:
1. Archives existing report(s) in ``reports/`` into ``reports/backup/`` with timestamps.
2. Generates a fresh self-contained interactive static HTML report into ``reports/index.html``.
3. Automatically commits and pushes to GitHub with ``[skip ci]``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger("agent_reach.daily_run.panel.publisher")

from agent_reach.daily_run.panel.export import export_panel_html

_BEIJING_TZ = timezone(timedelta(hours=8))


def find_repo_root() -> Path:
    """Detect repository root directory via git or directory structure."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        root = res.stdout.strip()
        if root and Path(root).is_dir():
            return Path(root)
    except Exception:
        pass
    # Fallback to relative path from this module
    return Path(__file__).resolve().parents[3]


def archive_existing_reports(
    reports_dir: Path,
    backup_dir: Path,
) -> list[str]:
    """Move existing HTML reports from reports_dir into backup_dir with timestamps."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    archived: list[str] = []

    if not reports_dir.exists():
        return archived

    for item in sorted(reports_dir.iterdir()):
        # Only archive files directly in reports_dir, do not touch backup subfolder
        if item.is_file() and item.suffix.lower() == ".html" and item.stat().st_size > 0:
            stem = item.stem
            # If the file already contains a timestamp (e.g. index_YYYYMMDD_HHMMSS), preserve its name
            if "_" in stem and any(ch.isdigit() for ch in stem):
                dest_name = item.name
                dest_path = backup_dir / dest_name
                counter = 1
                while dest_path.exists():
                    dest_name = f"{stem}_{counter}.html"
                    dest_path = backup_dir / dest_name
                    counter += 1
            else:
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc).astimezone(_BEIJING_TZ)
                    ts_str = mtime.strftime("%Y%m%d_%H%M%S")
                except Exception:
                    ts_str = datetime.now(_BEIJING_TZ).strftime("%Y%m%d_%H%M%S")

                dest_name = f"{stem}_{ts_str}.html"
                dest_path = backup_dir / dest_name

                counter = 1
                while dest_path.exists():
                    dest_name = f"{stem}_{ts_str}_{counter}.html"
                    dest_path = backup_dir / dest_name
                    counter += 1

            shutil.move(str(item), str(dest_path))
            archived.append(str(dest_path))
            logger.info("Archived previous report: {} -> {}", item.name, dest_name)

    return archived


def publish_panel_report(
    *,
    reports_dir: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    filename: Optional[str] = None,
    db_path: Optional[Path] = None,
    data_root: Optional[Path] = None,
    push_git: bool = True,
    job: str = "",
    commit_msg: str = "",
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Archive previous reports, generate new static HTML, and push to GitHub.

    Args:
        reports_dir: Target directory for HTML reports (default: ``<repo_root>/reports``).
        backup_dir: Target directory for archived reports (default: ``<reports_dir>/backup``).
        filename: Optional custom filename (default: ``index_<YYYYMMDD_HHMMSS>.html``).
        db_path: Optional SQLite DB path override.
        data_root: Optional daily_run data root path override.
        push_git: Whether to commit and git push to remote origin.
        job: Optional cron job name (e.g. morning, intraday, close).
        commit_msg: Optional custom git commit message.
        repo_root: Optional repository root path override.

    Returns:
        Summary dict containing paths and git status.
    """
    root = repo_root or find_repo_root()
    rep_dir = Path(reports_dir).expanduser() if reports_dir else root / "reports"
    bak_dir = Path(backup_dir).expanduser() if backup_dir else rep_dir / "backup"

    rep_dir.mkdir(parents=True, exist_ok=True)
    bak_dir.mkdir(parents=True, exist_ok=True)

    # 1. Archive previous report(s) to reports/backup
    archived = archive_existing_reports(rep_dir, bak_dir)

    # 2. Generate new static HTML into reports/index_<timestamp>.html
    if filename:
        target_name = filename
    else:
        now_ts = datetime.now(_BEIJING_TZ).strftime("%Y%m%d_%H%M%S")
        target_name = f"index_{now_ts}.html"

    target_html = rep_dir / target_name
    counter = 1
    stem = target_html.stem
    while target_html.exists():
        target_name = f"{stem}_{counter}.html"
        target_html = rep_dir / target_name
        counter += 1

    generated = export_panel_html(output_path=target_html, db_path=db_path, data_root=data_root)

    # Stable alias for Feishu / mobile links (short CDN URL: reports/index.html)
    stable_alias = rep_dir / "index.html"
    try:
        shutil.copy2(generated, stable_alias)
        logger.info("Updated stable panel alias: {}", stable_alias.name)
    except Exception as exc:
        logger.warning("Failed to write stable panel alias index.html: {}", exc)

    # Ensure .gitkeep exists in backup directory if empty
    gitkeep = bak_dir / ".gitkeep"
    if not any(bak_dir.iterdir()):
        gitkeep.touch(exist_ok=True)

    result: dict[str, Any] = {
        "success": True,
        "report_path": str(generated.resolve()),
        "archived_count": len(archived),
        "archived": archived,
        "git_committed": False,
        "git_pushed": False,
        "error": None,
    }

    # 3. Commit and upload to GitHub
    if push_git:
        try:
            # Stage reports directory
            subprocess.run(
                ["git", "add", "reports"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )

            # Check if there are staged changes
            diff = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(root),
                capture_output=True,
                timeout=15,
            )
            has_changes = diff.returncode != 0

            if has_changes:
                job_label = f" [{job}]" if job else ""
                now_label = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
                msg = commit_msg or f"docs(reports): update daily-run static report{job_label} ({now_label}) [skip ci]"

                subprocess.run(
                    ["git", "commit", "-m", msg],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                result["git_committed"] = True
                logger.info("Committed report changes: {}", msg)

                # Push to remote
                push_res = subprocess.run(
                    ["git", "push", "origin", "HEAD"],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                result["git_pushed"] = True
                logger.info("Pushed report changes to GitHub origin HEAD")
            else:
                logger.info("No report changes to commit.")
        except subprocess.CalledProcessError as err:
            err_msg = f"git command failed: {err.stderr or err.stdout or str(err)}"
            logger.warning(err_msg)
            result["error"] = err_msg
        except Exception as exc:
            err_msg = f"Git upload error: {exc}"
            logger.warning(err_msg)
            result["error"] = err_msg

    return result
