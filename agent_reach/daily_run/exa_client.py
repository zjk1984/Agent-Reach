# -*- coding: utf-8
"""Exa search via mcporter (with graceful fallback)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Optional

from agent_reach.utils.process import (
    EXA_MCP_URL,
    bundled_mcporter_config_path,
    mcporter_cli_prefix,
)


class ExaError(RuntimeError):
    pass


def format_exa_error(message: str, *, max_len: int = 200) -> str:
    """User-facing Exa error without mcporter stack traces."""
    text = (message or "").strip()
    if not text:
        return "Exa 搜索失败"
    first = text.splitlines()[0].strip()
    for prefix in ("[mcporter] ", "Error: "):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip()
    if "Ad-hoc servers require" in first or "Unknown MCP server" in first:
        return "Exa 未配置：请运行 mcporter config add exa https://mcp.exa.ai/mcp"
    return first[:max_len]


def is_exa_available() -> bool:
    if not shutil.which("mcporter"):
        return False

    cfg = bundled_mcporter_config_path()
    if cfg is not None:
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if "exa" in (data.get("mcpServers") or {}):
                return True
        except (json.JSONDecodeError, OSError):
            pass

    cmd = mcporter_cli_prefix() + ["config", "list"]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode == 0 and "exa" in (r.stdout or "").lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def web_search_exa(
    query: str,
    *,
    num_results: int = 3,
    timeout: int = 45,
) -> list[dict[str, Any]]:
    """Run exa.web_search_exa via mcporter; return parsed result list."""
    if not shutil.which("mcporter"):
        raise ExaError("mcporter 未安装")

    safe_query = query.replace('"', "'").replace("\\", " ")
    cfg = bundled_mcporter_config_path()
    if cfg is not None:
        call_expr = f'exa.web_search_exa(query: "{safe_query}", numResults: {num_results})'
        cmd = mcporter_cli_prefix() + ["call", call_expr]
    else:
        call_expr = f'web_search_exa(query: "{safe_query}", numResults: {num_results})'
        cmd = [
            "mcporter",
            "call",
            "--http-url",
            EXA_MCP_URL,
            call_expr,
        ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise ExaError(f"Exa 搜索超时：{query[:60]}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise ExaError(format_exa_error(err or "mcporter call failed"))

    return _parse_mcporter_output(proc.stdout or "")


def _parse_mcporter_output(text: str) -> list[dict[str, Any]]:
    """Best-effort parse mcporter JSON/text output into result dicts."""
    text = text.strip()
    if not text:
        return []

    # Try JSON array/object first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [_normalize_hit(x) for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("results", "data", "items"):
                if isinstance(data.get(key), list):
                    return [_normalize_hit(x) for x in data[key] if isinstance(x, dict)]
            return [_normalize_hit(data)]
    except json.JSONDecodeError:
        pass

    # Fallback: extract title/url lines
    hits: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("{"):
            continue
        url_match = re.search(r"https?://\S+", line)
        hits.append({
            "title": line[:120],
            "url": url_match.group(0) if url_match else "",
            "snippet": line[:300],
        })
    return hits[:5]


def _normalize_hit(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title") or item.get("name") or "")[:200],
        "url": str(item.get("url") or item.get("link") or ""),
        "snippet": str(item.get("snippet") or item.get("text") or item.get("summary") or "")[:400],
    }


def summarize_hits(hits: list[dict[str, Any]], *, max_chars: int = 280) -> str:
    if not hits:
        return ""
    parts = []
    for h in hits[:3]:
        title = h.get("title") or h.get("url") or "result"
        parts.append(str(title)[:80])
    summary = " · ".join(parts)
    return summary[:max_chars]
