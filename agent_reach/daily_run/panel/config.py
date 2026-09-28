# -*- coding: utf-8 -*-
"""Configuration reader for daily-run mission control panel."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Any, Optional

from agent_reach.daily_run.settings import effective_settings, load_settings

_DEFAULT_PANEL_CFG: dict[str, Any] = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 8788,
    "url": "auto",
    "url_mode": "htmlpreview",  # "htmlpreview", "pages", or "raw"
    "branch": "main",
    "card_link_enabled": True,
}


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
    return Path(__file__).resolve().parents[3]


def find_latest_report_file(
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Optional[Path]:
    """Find the newest generated static HTML report in reports/ or reports/backup/."""
    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    rep_dir = Path(reports_dir).expanduser() if reports_dir else root / "reports"
    if not rep_dir.exists():
        return None

    def _collect_candidates(d: Path) -> list[Path]:
        if not d.exists() or not d.is_dir():
            return []
        items = []
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() == ".html" and f.stat().st_size > 0:
                items.append(f)
        return items

    candidates = _collect_candidates(rep_dir)
    if not candidates:
        candidates = _collect_candidates(rep_dir / "backup")

    if not candidates:
        return None

    # Prefer files starting with 'index', sorted by (mtime, name) descending
    index_files = [f for f in candidates if f.name.startswith("index")]
    target_pool = index_files if index_files else candidates
    target_pool.sort(key=lambda f: (f.stat().st_mtime, f.name), reverse=True)
    return target_pool[0]


def detect_github_repo(
    settings: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path | str] = None,
) -> tuple[str, str]:
    """Detect (owner, repo) from settings, GITHUB_REPOSITORY env, or git remote origin."""
    cfg = panel_cfg(settings)
    custom_repo = str(cfg.get("github_repo") or "").strip()
    if custom_repo and "/" in custom_repo:
        parts = custom_repo.split("/", 1)
        return parts[0].strip(), parts[1].strip()

    gh_env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if gh_env and "/" in gh_env:
        parts = gh_env.split("/", 1)
        return parts[0].strip(), parts[1].strip()

    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        url = res.stdout.strip()
        m = re.search(r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?", url)
        if m:
            return m.group("owner"), m.group("repo")
    except Exception:
        pass

    return "zjk1984", "Agent-Reach"


def panel_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return effective panel config merged with defaults."""
    raw = settings if settings is not None else load_settings()
    eff = effective_settings(raw) if raw else {}
    user_block = eff.get("panel")
    if not isinstance(user_block, dict):
        user_block = {}
    merged = dict(_DEFAULT_PANEL_CFG)
    merged.update(user_block)
    return merged


def panel_url(
    settings: Optional[dict[str, Any]] = None,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> str:
    """Return the browser-viewable dashboard URL.

    Resolves to the latest static report in reports/ via htmlpreview.github.io
    (or GitHub Pages) unless explicitly overridden.
    """
    url = os.environ.get("AGENT_REACH_PANEL_URL", "").strip()
    if url:
        return url

    cfg = panel_cfg(settings)
    custom_url = str(cfg.get("url") or "").strip()
    # If the user explicitly configured a custom remote URL (not auto/localhost:8788), respect it
    if custom_url and custom_url.lower() not in (
        "auto",
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "127.0.0.1:8788",
    ):
        return custom_url

    latest_file = find_latest_report_file(reports_dir=reports_dir, repo_root=repo_root)
    filename = latest_file.name if latest_file else "index.html"
    owner, repo = detect_github_repo(settings, repo_root=repo_root)
    branch = str(cfg.get("branch") or "main")
    mode = str(cfg.get("url_mode") or "htmlpreview").lower()

    if mode in ("pages", "github_pages") or cfg.get("github_pages_base"):
        base = cfg.get("github_pages_base") or f"https://{owner}.github.io/{repo}"
        return f"{base.rstrip('/')}/reports/{filename}"
    elif mode in ("raw", "blob"):
        return f"https://github.com/{owner}/{repo}/blob/{branch}/reports/{filename}"
    else:  # htmlpreview (default — directly renders static HTML in any browser)
        return f"https://htmlpreview.github.io/?https://github.com/{owner}/{repo}/blob/{branch}/reports/{filename}"


def panel_card_link_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    """Check whether card link to the panel should be attached to Feishu notifications."""
    cfg = panel_cfg(settings)
    return bool(cfg.get("enabled", True) and cfg.get("card_link_enabled", True))


def format_panel_card_header(
    settings: Optional[dict[str, Any]] = None,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Optional[str]:
    """Format the top header line for Feishu cards: 🖥️ 实时大屏：[url](url)."""
    if not panel_card_link_enabled(settings):
        return None
    url = panel_url(settings, reports_dir=reports_dir, repo_root=repo_root)
    return f"🖥️ 实时大屏：[{url}]({url})"


def prepend_panel_card_header(
    markdown: str,
    settings: Optional[dict[str, Any]] = None,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> str:
    """Prepend the panel link header at the very top of markdown, removing any duplicate links."""
    if not panel_card_link_enabled(settings):
        return markdown
    header = format_panel_card_header(settings, reports_dir=reports_dir, repo_root=repo_root)
    if not header:
        return markdown

    # Strip any existing 实时大屏 lines anywhere in markdown to prevent duplication
    clean_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if "实时大屏" in stripped and ("http://" in stripped or "https://" in stripped):
            continue
        clean_lines.append(line)

    cleaned = "\n".join(clean_lines).strip()
    if not cleaned:
        return header
    return f"{header}\n\n{cleaned}"

