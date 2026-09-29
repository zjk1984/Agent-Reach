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

_REPO_CACHE: Optional[tuple[str, str]] = None
_REPO_ROOT_CACHE: Optional[Path] = None
_REMOTE_REPORT_CACHE: dict[str, tuple[float, Optional[str]]] = {}


_DEFAULT_PANEL_CFG: dict[str, Any] = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 8788,
    "url": "auto",
    # pages: GitHub Pages serves HTML with text/html (browser + Feishu in-app OK).
    # jsdelivr/raw return text/plain — browsers show source, not the dashboard.
    "url_mode": "pages",
    "branch": "main",
    "card_link_enabled": True,
    "provenance_in_cards": True,
    "publish_before_card": False,
    "fetch_remote_before_url": False,
    "stable_url_filename": "index.html",
    "panel_public_path": "reports/index.html",
    "github_pages_base": "",
}


def find_repo_root() -> Path:
    """Detect repository root directory via git or directory structure."""
    global _REPO_ROOT_CACHE
    if _REPO_ROOT_CACHE is not None:
        return _REPO_ROOT_CACHE
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        )
        root = res.stdout.strip()
        if root and Path(root).is_dir():
            _REPO_ROOT_CACHE = Path(root)
            return _REPO_ROOT_CACHE
    except Exception:
        pass
    _REPO_ROOT_CACHE = Path(__file__).resolve().parents[3]
    return _REPO_ROOT_CACHE


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

    def _build_url(rel_path: str) -> str:
        return build_public_report_url(rel_path, repo_root=root)

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


def github_pages_base_url(
    settings: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path | str] = None,
) -> str:
    """Return GitHub Pages site base URL for this repository."""
    cfg = panel_cfg(settings)
    custom = str(cfg.get("github_pages_base") or "").strip()
    if custom:
        return custom.rstrip("/")
    owner, repo = detect_github_repo(settings, repo_root=repo_root)
    return f"https://{owner}.github.io/{repo}"


def build_public_report_url(
    relative_path: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path | str] = None,
) -> str:
    """Build a browser-viewable URL for a report file under reports/."""
    cfg = panel_cfg(settings)
    owner, repo = detect_github_repo(settings, repo_root=repo_root)
    branch = str(cfg.get("branch") or "main")
    rel = relative_path.lstrip("/")
    mode = str(cfg.get("url_mode") or "pages").lower()

    if mode in ("pages", "github_pages") or cfg.get("github_pages_base"):
        return f"{github_pages_base_url(settings, repo_root=repo_root)}/{rel}"
    if mode in ("raw", "rawgithub"):
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel}"
    if mode in ("htmlpreview", "preview"):
        gh_blob = f"https://github.com/{owner}/{repo}/blob/{branch}/{rel}"
        return f"https://htmlpreview.github.io/?{gh_blob}"
    # jsdelivr — note: serves HTML as text/plain; not suitable for in-browser viewing
    return f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{rel}"


def find_latest_remote_report_file(
    *,
    branch: Optional[str] = None,
    repo_root: Optional[Path | str] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return the newest reports/*.html filename known on origin/<branch> (excluding backup/)."""
    import time as _time

    cfg = panel_cfg(settings)
    br = branch or str(cfg.get("branch") or "main")
    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    cache_key = f"{root}:{br}"
    cached = _REMOTE_REPORT_CACHE.get(cache_key)
    if cached and (_time.time() - cached[0]) < 60:
        return cached[1]
    try:
        if cfg.get("fetch_remote_before_url"):
            subprocess.run(
                ["git", "fetch", "origin", br],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=20,
            )
        res = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", f"origin/{br}", "reports/"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        names: list[str] = []
        for line in res.stdout.splitlines():
            path = line.strip().replace("\\", "/")
            if not path.endswith(".html"):
                continue
            if "/backup/" in path:
                continue
            if not path.startswith("reports/"):
                continue
            names.append(path.split("/")[-1])
        if not names:
            _REMOTE_REPORT_CACHE[cache_key] = (_time.time(), None)
            return None
        stable = str(cfg.get("stable_url_filename") or "index.html")
        if stable in names:
            _REMOTE_REPORT_CACHE[cache_key] = (_time.time(), stable)
            return stable
        index_ts = sorted(
            [n for n in names if n.startswith("index_")],
            reverse=True,
        )
        chosen = index_ts[0] if index_ts else sorted(names, reverse=True)[0]
        _REMOTE_REPORT_CACHE[cache_key] = (_time.time(), chosen)
        return chosen
    except Exception:
        _REMOTE_REPORT_CACHE[cache_key] = (_time.time(), None)
        return None


def resolve_panel_report_filename(
    *,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """Pick a report filename whose public URL is most likely to resolve on GitHub."""
    cfg = panel_cfg(settings)
    stable = str(cfg.get("stable_url_filename") or "index.html")
    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    rep_dir = Path(reports_dir).expanduser() if reports_dir else root / "reports"

    remote_name = find_latest_remote_report_file(repo_root=root, settings=settings)
    if remote_name:
        return remote_name

    if (rep_dir / stable).exists() and (rep_dir / stable).stat().st_size > 0:
        return stable

    latest_local = find_latest_report_file(reports_dir=rep_dir, repo_root=root)
    if latest_local:
        return latest_local.name
    return stable


def detect_github_repo(
    settings: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path | str] = None,
) -> tuple[str, str]:
    """Detect (owner, repo) from settings, GITHUB_REPOSITORY env, or git remote origin."""
    global _REPO_CACHE
    if settings is None and repo_root is None and _REPO_CACHE is not None:
        return _REPO_CACHE

    cfg = panel_cfg(settings)
    custom_repo = str(cfg.get("github_repo") or "").strip()
    if custom_repo and "/" in custom_repo:
        parts = custom_repo.split("/", 1)
        owner, repo = parts[0].strip(), parts[1].strip()
        if settings is None and repo_root is None:
            _REPO_CACHE = (owner, repo)
        return owner, repo

    gh_env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if gh_env and "/" in gh_env:
        parts = gh_env.split("/", 1)
        owner, repo = parts[0].strip(), parts[1].strip()
        if settings is None and repo_root is None:
            _REPO_CACHE = (owner, repo)
        return owner, repo

    root = Path(repo_root).expanduser() if repo_root else find_repo_root()
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        )
        url = res.stdout.strip()
        m = re.search(r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?", url)
        if m:
            owner, repo = m.group("owner"), m.group("repo")
            if settings is None and repo_root is None:
                _REPO_CACHE = (owner, repo)
            return owner, repo
    except Exception:
        pass

    fallback = ("zjk1984", "Agent-Reach")
    if settings is None and repo_root is None:
        _REPO_CACHE = fallback
    return fallback


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
    """Return a browser-viewable dashboard URL (GitHub Pages by default)."""
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

    mode = str(cfg.get("url_mode") or "pages").lower()
    if mode in ("pages", "github_pages") or cfg.get("github_pages_base"):
        public_path = str(cfg.get("panel_public_path") or "reports/index.html").lstrip("/")
        return f"{github_pages_base_url(settings, repo_root=repo_root)}/{public_path}"

    filename = resolve_panel_report_filename(
        reports_dir=reports_dir,
        repo_root=repo_root,
        settings=settings,
    )
    return build_public_report_url(f"reports/{filename}", settings=settings, repo_root=repo_root)


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


def maybe_publish_panel_before_card(
    settings: Optional[dict[str, Any]] = None,
    *,
    job: str = "feishu",
    repo_root: Optional[Path | str] = None,
) -> None:
    """Optionally publish + push panel HTML before embedding the card link."""
    cfg = panel_cfg(settings)
    if not cfg.get("publish_before_card"):
        return
    try:
        from agent_reach.daily_run.panel.publisher import publish_panel_report

        publish_panel_report(push_git=True, job=job, repo_root=repo_root)
    except Exception:
        pass


def prepend_panel_card_header(
    markdown: str,
    settings: Optional[dict[str, Any]] = None,
    reports_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> str:
    """Prepend the panel link header at the very top of markdown, removing any duplicate links."""
    if not panel_card_link_enabled(settings):
        return markdown
    maybe_publish_panel_before_card(settings, repo_root=repo_root)
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

