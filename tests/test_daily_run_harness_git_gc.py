# -*- coding: utf-8
"""Garbage collection for orphaned harness/branches/<slug>/ dirs."""

import os
import subprocess
import time

from agent_reach.daily_run.harness_git import (
    branch_slug,
    gc_stale_branch_dirs,
    list_known_branch_slugs,
)


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    subprocess.run(["git", "branch", "cursor/keep-me"], cwd=path, check=True)


def test_list_known_branch_slugs_includes_local_branches(tmp_path):
    _init_repo(tmp_path)
    slugs = list_known_branch_slugs(cwd=tmp_path)
    assert branch_slug("cursor/keep-me") in slugs


def test_gc_removes_only_orphaned_old_dirs(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    harness_root = tmp_path / ".harness"
    branches_dir = harness_root / "branches"
    branches_dir.mkdir(parents=True)

    keep_branch_dir = branches_dir / branch_slug("cursor/keep-me")
    keep_branch_dir.mkdir()
    orphan_old_dir = branches_dir / "long-gone-branch"
    orphan_old_dir.mkdir()
    orphan_new_dir = branches_dir / "just-created-branch"
    orphan_new_dir.mkdir()

    # Backdate the old orphan so it clears the min_age_days guard; leave the
    # new orphan at current mtime so it's protected.
    old_ts = time.time() - 10 * 86400
    os.utime(orphan_old_dir, (old_ts, old_ts))

    monkeypatch.setattr("agent_reach.daily_run.harness_git._harness_root", lambda: harness_root)

    result = gc_stale_branch_dirs(min_age_days=3, dry_run=False, cwd=tmp_path)

    assert result["removed"] == ["long-gone-branch"]
    assert set(result["kept"]) == {branch_slug("cursor/keep-me"), "just-created-branch"}
    assert not orphan_old_dir.exists()
    assert orphan_new_dir.exists()
    assert keep_branch_dir.exists()


def test_gc_dry_run_does_not_delete(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    harness_root = tmp_path / ".harness"
    branches_dir = harness_root / "branches"
    branches_dir.mkdir(parents=True)
    orphan_dir = branches_dir / "long-gone-branch"
    orphan_dir.mkdir()
    old_ts = time.time() - 10 * 86400
    os.utime(orphan_dir, (old_ts, old_ts))

    monkeypatch.setattr("agent_reach.daily_run.harness_git._harness_root", lambda: harness_root)

    result = gc_stale_branch_dirs(min_age_days=3, dry_run=True, cwd=tmp_path)

    assert result["removed"] == ["long-gone-branch"]
    assert result["dry_run"] is True
    assert orphan_dir.exists()  # dry-run must not delete


def test_gc_no_branches_dir_returns_empty(tmp_path, monkeypatch):
    harness_root = tmp_path / ".harness"
    monkeypatch.setattr("agent_reach.daily_run.harness_git._harness_root", lambda: harness_root)
    result = gc_stale_branch_dirs(cwd=tmp_path)
    assert result == {"removed": [], "kept": [], "scanned": 0}
