# -*- coding: utf-8 -*-
"""Configuration reader for daily-run mission control panel."""

from __future__ import annotations

from datetime import datetime
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


def list_recent_report_snapshots(
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    limit: int = 15,
    current_file: Optional[Path | str] = None,
) -> list[dict[str, Any]]:
    """List recent report snapshots from reports/ and reports/backup/ for dropdown selection.

    Returns a list of dicts:
    [
      {
        "filename": "index_20260928_150659.html",
        "relative_path": "reports/index_20260928_150659.html",
        "is_backup": False,
        "label": "2026-09-28 15:06 (最新)",
        "url": "https://htmlpreview.github.io/?https://github.com/...",
        "mtime": 1790000000.0,
      }, ...
    ]
    """
    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    rep_dir = Path(reports_dir).expanduser() if reports_dir else root / "reports"
    if not rep_dir.exists():
        return []

    owner, repo = detect_github_repo(repo_root=root)
    cfg = panel_cfg()
    branch = str(cfg.get("branch") or "main")
    mode = str(cfg.get("url_mode") or "htmlpreview").lower()

    def _build_url(rel_path: str) -> str:
        if mode in ("pages", "github_pages") or cfg.get("github_pages_base"):
            base = cfg.get("github_pages_base") or f"https://{owner}.github.io/{repo}"
            return f"{base.rstrip('/')}/{rel_path}"
        elif mode in ("raw", "blob"):
            return f"https://github.com/{owner}/{repo}/blob/{branch}/{rel_path}"
        else:
            return f"https://htmlpreview.github.io/?https://github.com/{owner}/{repo}/blob/{branch}/{rel_path}"

    files_info: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Optional current file being exported
    if current_file:
        cur_p = Path(current_file)
        files_info.append({
            "file": cur_p,
            "is_backup": False,
            "rel": f"reports/{cur_p.name}",
            "is_current": True,
        })
        seen_names.add(cur_p.name)

    # 1. Main reports dir (current latest)
    for f in rep_dir.iterdir():
        if f.name not in seen_names and f.is_file() and f.suffix.lower() == ".html" and f.stat().st_size > 0:
            files_info.append({
                "file": f,
                "is_backup": False,
                "rel": f"reports/{f.name}",
                "is_current": False,
            })
            seen_names.add(f.name)

    # 2. Backup reports dir (historical)
    bak_dir = rep_dir / "backup"
    if bak_dir.exists() and bak_dir.is_dir():
        for f in bak_dir.iterdir():
            if f.name not in seen_names and f.is_file() and f.suffix.lower() == ".html" and f.stat().st_size > 0:
                files_info.append({
                    "file": f,
                    "is_backup": True,
                    "rel": f"reports/backup/{f.name}",
                    "is_current": False,
                })
                seen_names.add(f.name)

    # Sort descending: current file first, then non-backup (primary) files, then by filename timestamp, then mtime
    def _sort_key(x: dict[str, Any]) -> tuple[int, int, str, float]:
        is_cur = 1 if x.get("is_current") else 0
        is_primary = 1 if not x.get("is_backup") else 0
        m = re.search(r"(\d{8}_\d{6})", x["file"].name)
        ts_str = m.group(1) if m else ""
        try:
            mt = x["file"].stat().st_mtime
        except Exception:
            mt = 0.0
        return (is_cur, is_primary, ts_str, mt)

    files_info.sort(key=_sort_key, reverse=True)

    items: list[dict[str, Any]] = []
    for idx, info in enumerate(files_info[:limit]):
        f = info["file"]
        stem = f.stem
        # Format label from filename e.g. index_20260928_150659 -> 2026-09-28 15:06
        m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", stem)
        if m:
            time_label = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
        else:
            try:
                dt = datetime.fromtimestamp(f.stat().st_mtime)
                time_label = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                time_label = stem

        is_latest = (idx == 0 and not info["is_backup"])
        display_label = f"{time_label} (最新)" if is_latest else time_label

        try:
            mtime_val = f.stat().st_mtime
        except Exception:
            mtime_val = 0.0

        items.append({
            "filename": f.name,
            "relative_path": info["rel"],
            "is_backup": info["is_backup"],
            "label": display_label,
            "url": _build_url(info["rel"]),
            "mtime": mtime_val,
        })

    return items


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


def panel_provenance_in_cards_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    """Whether Feishu cards should include the compact D1~D6 provenance strip."""
    cfg = panel_cfg(settings)
    return bool(cfg.get("enabled", True) and cfg.get("provenance_in_cards", True))


def format_data_provenance_line(settings: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Compact D1~D6 feed status for Feishu card headers."""
    if not panel_provenance_in_cards_enabled(settings):
        return None
    try:
        from agent_reach.daily_run.data_router import format_provenance_compact_line

        return format_provenance_compact_line(settings=settings)
    except Exception:
        return None


def format_panel_card_header(
    settings: Optional[dict[str, Any]] = None,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Optional[str]:
    """Format the top header line for Feishu cards: 🖥️ 实时大屏：[url](url)."""
    if not panel_card_link_enabled(settings):
        return None
    url = panel_url(settings, reports_dir=reports_dir, repo_root=repo_root)
    header = f"🖥️ 实时大屏：[{url}]({url})"
    prov_line = format_data_provenance_line(settings)
    if prov_line:
        return f"{header}\n{prov_line}"
    return header


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

    # Strip any existing 实时大屏 / 数据源 lines anywhere in markdown to prevent duplication
    clean_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if "实时大屏" in stripped and ("http://" in stripped or "https://" in stripped):
            continue
        if stripped.startswith("📡 数据源："):
            continue
        clean_lines.append(line)

    cleaned = "\n".join(clean_lines).strip()
    if not cleaned:
        return header
    return f"{header}\n\n{cleaned}"

