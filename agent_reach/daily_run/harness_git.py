# -*- coding: utf-8
"""Git branch-aware harness paths (dsh-memory-evolve style isolation)."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _harness_root() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "harness"


def branch_overlay_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    harness = dict((settings or {}).get("harness") or {})
    raw = dict(harness.get("branch_overlay") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "use_root_for_main": raw.get("use_root_for_main", True) is not False,
        "main_names": {str(x).lower() for x in (raw.get("main_names") or ["main", "master"])},
    }


def detect_git_branch(*, cwd: Optional[Path] = None) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        branch = (proc.stdout or "").strip()
        if proc.returncode == 0 and branch and branch != "HEAD":
            return branch
    except (OSError, subprocess.SubprocessError):
        pass
    return "detached"


def branch_slug(branch: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(branch or "detached")).strip("-")
    return slug[:80] or "detached"


def resolve_harness_paths(settings: Optional[dict[str, Any]] = None) -> dict[str, Path]:
    cfg = branch_overlay_cfg(settings)
    root = _harness_root()
    branch = detect_git_branch()
    if not cfg["enabled"] or (cfg["use_root_for_main"] and branch.lower() in cfg["main_names"]):
        base = root
    else:
        base = root / "branches" / branch_slug(branch)
    base.mkdir(parents=True, exist_ok=True)
    return {
        "root": base,
        "branch": branch,
        "state": base / "harness_state.json",
        "refinements": base / "refinements.jsonl",
        "snapshots": base / "snapshots",
        "registry": base / "study_registry.json",
        "audit": root / "apply_audit.jsonl",
    }


def resolve_harness_state_path(settings: Optional[dict[str, Any]] = None) -> Path:
    return resolve_harness_paths(settings)["state"]


def list_known_branch_slugs(*, cwd: Optional[Path] = None) -> set[str]:
    """Slugs for every local + remote-tracking branch (matches branch_slug())."""
    try:
        proc = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    slugs: set[str] = set()
    for raw in (proc.stdout or "").splitlines():
        name = raw.strip()
        if not name:
            continue
        # Strip "origin/" (or any remote name) so local + remote copies of the
        # same branch collapse to one slug.
        name = name.split("/", 1)[1] if name.startswith("origin/") else name
        slugs.add(branch_slug(name))
    return slugs


def gc_stale_branch_dirs(
    *,
    min_age_days: int = 3,
    dry_run: bool = False,
    cwd: Optional[Path] = None,
) -> dict[str, Any]:
    """Remove ``harness/branches/<slug>/`` dirs whose branch no longer exists.

    Branch-isolated harness state (see ``resolve_harness_paths``) is never
    cleaned up when a feature branch is merged/deleted, so it accumulates
    forever. Guarded by ``min_age_days`` (mtime) so a dir isn't removed the
    moment a branch is briefly unavailable (e.g. mid-rename).
    """
    branches_dir = _harness_root() / "branches"
    if not branches_dir.exists():
        return {"removed": [], "kept": [], "scanned": 0}

    known = list_known_branch_slugs(cwd=cwd)
    known.add("detached")  # always-valid fallback slug, never orphaned
    now = datetime.now(timezone.utc).timestamp()
    min_age_seconds = max(0, min_age_days) * 86400

    removed: list[str] = []
    kept: list[str] = []
    for entry in sorted(branches_dir.iterdir()):
        if not entry.is_dir():
            continue
        slug = entry.name
        if slug in known:
            kept.append(slug)
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            age = 0
        if age < min_age_seconds:
            kept.append(slug)
            continue
        removed.append(slug)
        if not dry_run:
            shutil.rmtree(entry, ignore_errors=True)

    return {
        "removed": removed,
        "kept": kept,
        "scanned": len(removed) + len(kept),
        "dry_run": dry_run,
    }
