# -*- coding: utf-8 -*-
"""Development / coordinator project progress (Feishu) — markdown file → card."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai

TITLE_PREFIX = "Agent-Reach 开发进展"
DEFAULT_REPORT_PATH = (
    Path.home() / ".agent-reach" / "daily_run" / "reports" / "dev-project-progress.md"
)
FEISHU_BODY_MAX_CHARS = 3200


def _ops_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    raw = settings.get("ops")
    return dict(raw) if isinstance(raw, dict) else {}


def dev_project_progress_feishu_enabled(settings: dict[str, Any]) -> bool:
    block = _ops_cfg(settings).get("dev_project_progress_feishu") or {}
    return block.get("enabled") is True


def default_dev_project_progress_path() -> Path:
    return DEFAULT_REPORT_PATH


def resolve_dev_project_progress_path(file_arg: Optional[str]) -> Path:
    if file_arg and str(file_arg).strip():
        return Path(file_arg).expanduser().resolve()
    return default_dev_project_progress_path()


def load_dev_project_progress_markdown(path: Optional[Path] = None, *, file_arg: Optional[str] = None) -> str:
    p = path if path is not None else resolve_dev_project_progress_path(file_arg)
    if not p.is_file():
        raise FileNotFoundError(f"dev project progress markdown not found: {p}")
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"dev project progress markdown is empty: {p}")
    return text


_NO_BLOCKER_MARKERS = frozenset(
    {
        "无",
        "无。",
        "none",
        "n/a",
        "—",
        "-",
        "暂无",
        "无阻塞",
        "无（",
    }
)


def _line_indicates_no_blocker(line: str) -> bool:
    stripped = line.strip().lstrip("-*• ").strip()
    if not stripped:
        return True
    low = stripped.lower()
    for marker in _NO_BLOCKER_MARKERS:
        if low == marker.lower() or low.startswith(marker.lower()):
            return True
    return False


def extract_blocker_hints(markdown: str) -> list[str]:
    """Parse markdown for blocker bullets (coordinator-authored)."""
    hints: list[str] = []
    in_blocker_section = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if re.match(r"^#+\s*阻塞", line) or re.match(r"^\*\*阻塞\*\*", line):
            in_blocker_section = True
            continue
        if in_blocker_section:
            if re.match(r"^#+\s", line) and "阻塞" not in line:
                break
            if line.strip().startswith("-") or line.strip().startswith("*"):
                item = line.strip().lstrip("-* ").strip()
                if item and not _line_indicates_no_blocker(item):
                    hints.append(item)
            elif line.strip() == "":
                continue
            elif line.strip().startswith("**") and "阻塞" in line:
                continue
            else:
                break
    if not hints:
        for line in markdown.splitlines():
            if "阻塞" in line and line.strip().startswith("-"):
                item = line.strip().lstrip("- ").strip()
                if item and not _line_indicates_no_blocker(item):
                    hints.append(item)
    return hints


def feishu_template_for_dev_markdown(markdown: str) -> str:
    blockers = extract_blocker_hints(markdown)
    if blockers:
        return "red"
    if re.search(r"(?m)^#+\s*已完成", markdown) or re.search(r"(?m)^\*\*已完成", markdown):
        return "green"
    return "blue"


def compact_dev_progress_for_feishu(markdown: str, *, max_chars: int = FEISHU_BODY_MAX_CHARS) -> str:
    body = markdown.strip()
    if len(body) <= max_chars:
        return body
    trimmed = body[: max_chars - 80].rstrip()
    return f"{trimmed}\n\n_… 正文已截断；完整版见 `{DEFAULT_REPORT_PATH}` _"


def dev_project_progress_feishu_card(
    markdown: str,
    *,
    as_of: Optional[str] = None,
) -> tuple[str, str, str]:
    d = as_of or today_shanghai().isoformat()
    title = f"🛠 {TITLE_PREFIX} · {d}"
    body = compact_dev_progress_for_feishu(markdown)
    tpl = feishu_template_for_dev_markdown(markdown)
    return title, body, tpl