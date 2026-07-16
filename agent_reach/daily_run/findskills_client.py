# -*- coding: utf-8
"""Search OpenClaw skills via zjk1984/findskills (ClawHub + GitHub sources)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import requests

FINDSKILLS_REPO_DEFAULT = "https://github.com/zjk1984/findskills.git"
CLAWHUB_SEARCH_URL = "https://clawhub.ai/api/v1/search"
CLAWHUB_MIRROR_URL = "https://skills.volces.com/api/v1/search"


class FindSkillsError(RuntimeError):
    pass


def findskills_root(settings: Optional[dict[str, Any]] = None) -> Path:
    cfg = (settings or {}).get("findskills") or {}
    custom = cfg.get("install_dir")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".agent-reach" / "findskills"


def _json_bridge_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "findskills_json.mjs"


def is_findskills_available(settings: Optional[dict[str, Any]] = None) -> bool:
    if not shutil.which("node"):
        return False
    root = findskills_root(settings)
    return (root / "src" / "search-engine.js").is_file()


def ensure_findskills(settings: Optional[dict[str, Any]] = None) -> Path:
    """Clone zjk1984/findskills and npm install if missing."""
    cfg = (settings or {}).get("findskills") or {}
    root = findskills_root(settings)
    repo = str(cfg.get("repo") or FINDSKILLS_REPO_DEFAULT)

    if not (root / "src" / "search-engine.js").is_file():
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            shutil.rmtree(root)
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", repo, str(root)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "git clone failed").strip()
            raise FindSkillsError(f"无法克隆 findskills：{err}")

    if not (root / "node_modules").is_dir():
        npm = shutil.which("npm") or "npm"
        proc = subprocess.run(
            [npm, "install", "--omit=dev"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "npm install failed").strip()
            raise FindSkillsError(f"findskills 依赖安装失败：{err}")

    return root


def _normalize_skill(raw: dict[str, Any]) -> dict[str, Any]:
    slug = str(raw.get("slug") or raw.get("name") or "")
    name = str(raw.get("name") or raw.get("displayName") or slug)
    description = str(raw.get("description") or raw.get("summary") or "")[:400]
    install = str(raw.get("installCommand") or (f"clawhub install {slug}" if slug else ""))
    source_url = str(
        raw.get("sourceUrl")
        or raw.get("repository")
        or (f"https://clawhub.ai/skills/{slug}" if slug else "")
    )
    return {
        "name": name,
        "slug": slug,
        "description": description,
        "tags": list(raw.get("tags") or []),
        "quality_score": raw.get("qualityScore") or raw.get("quality_score") or 0,
        "downloads": raw.get("downloads") or 0,
        "verified": bool(raw.get("verified")),
        "install_command": install,
        "source_url": source_url,
        "source": raw.get("source") or "clawhub",
    }


def _search_via_node(
    query: str,
    *,
    limit: int,
    timeout: int,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    root = ensure_findskills(settings)
    script = _json_bridge_script()
    if not script.is_file():
        raise FindSkillsError(f"缺少 JSON bridge：{script}")

    env = {**os.environ, "FINDSKILLS_ROOT": str(root)}
    proc = subprocess.run(
        ["node", str(script), "search", query, "--limit", str(limit)],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise FindSkillsError(err or "findskills search failed")

    payload = json.loads(proc.stdout or "{}")
    if not payload.get("success"):
        msg = (payload.get("error") or {}).get("message") or "findskills 搜索失败"
        raise FindSkillsError(str(msg))

    data = payload.get("data") or {}
    results = data.get("results") or []
    return [_normalize_skill(r) for r in results if isinstance(r, dict)]


def _search_via_clawhub_api(query: str, *, limit: int, timeout: int) -> list[dict[str, Any]]:
    """Direct ClawHub API fallback (same endpoints as findskills)."""
    params = {"q": query, "limit": limit}
    for url in (CLAWHUB_SEARCH_URL, CLAWHUB_MIRROR_URL):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            results = body.get("results") or []
            if not results:
                continue
            skills: list[dict[str, Any]] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                meta = item.get("metaContent") or {}
                skill_md = meta.get("skillMd") or ""
                name = meta.get("displayName") or item.get("displayName") or item.get("slug")
                desc = (
                    meta.get("DisplayDescription")
                    or item.get("summary")
                    or ""
                )
                if not desc and "description:" in skill_md:
                    desc = skill_md.split("description:", 1)[1].split("\n", 1)[0].strip()
                slug = str(item.get("slug") or "")
                skills.append(
                    _normalize_skill(
                        {
                            "name": name,
                            "slug": slug,
                            "description": desc,
                            "qualityScore": item.get("score") or 0,
                            "installCommand": f"clawhub install {slug}" if slug else "",
                            "sourceUrl": f"https://clawhub.ai/skills/{slug}" if slug else "",
                        }
                    )
                )
            return skills[:limit]
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            continue
    return []


def search_skills(
    query: str,
    *,
    limit: int = 3,
    timeout: int = 45,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Search skills; prefers zjk1984/findskills via node, falls back to ClawHub API."""
    cfg = (settings or {}).get("findskills") or {}
    if cfg.get("enabled", True) is False:
        return []

    limit = int(cfg.get("result_limit", limit))
    timeout = int(cfg.get("timeout", timeout))

    if shutil.which("node"):
        try:
            return _search_via_node(query, limit=limit, timeout=timeout, settings=settings)
        except (FindSkillsError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass

    return _search_via_clawhub_api(query, limit=limit, timeout=timeout)


def summarize_skills(skills: list[dict[str, Any]], *, max_chars: int = 280) -> str:
    if not skills:
        return ""
    parts: list[str] = []
    for s in skills[:3]:
        name = s.get("name") or s.get("slug") or "skill"
        score = s.get("quality_score")
        if score:
            parts.append(f"{name}({score})")
        else:
            parts.append(str(name)[:60])
    return " · ".join(parts)[:max_chars]


def run_findskills_queries(
    queries: list[dict[str, str]],
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Run multiple findskills searches (parallel when possible)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cfg = (settings or {}).get("findskills") or {}
    if cfg.get("enabled", True) is False:
        return []

    wr_cfg = (settings or {}).get("weekly_report") or {}
    max_q = int(wr_cfg.get("max_findskills_queries", cfg.get("max_queries", 2)))
    limit = int(cfg.get("result_limit", 3))
    timeout = int(cfg.get("timeout", 45))
    queries = queries[:max_q]
    if not queries:
        return []

    def _one(q: dict[str, str]) -> dict[str, Any]:
        query = q.get("query") or ""
        try:
            skills = search_skills(query, limit=limit, timeout=timeout, settings=settings)
            return {
                **q,
                "skills": skills,
                "summary": summarize_skills(skills),
                "success": bool(skills),
            }
        except FindSkillsError as exc:
            return {**q, "skills": [], "summary": str(exc), "success": False}

    workers = min(len(queries), 2)
    ordered: list[Optional[dict[str, Any]]] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, q): i for i, q in enumerate(queries)}
        for fut in as_completed(futures):
            ordered[futures[fut]] = fut.result()
    return [r for r in ordered if r is not None]


def build_weekly_skill_queries(
    *,
    hot_sectors: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    experience_snippets: list[str],
) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []
    if hot_sectors:
        top = hot_sectors[0].get("sector") or hot_sectors[0].get("name") or ""
        if top:
            queries.append(
                {"query": f"OpenClaw agent skill trading {top} sector research", "label": f"{top} 相关技能"}
            )
    if holdings:
        names = " ".join(str(h.get("name") or "") for h in holdings[:3]).strip()
        if names:
            queries.append(
                {"query": f"OpenClaw agent skill stock portfolio analysis {names}", "label": "持仓分析技能"}
            )
    if experience_snippets and len(queries) < 2:
        snippet = experience_snippets[0][:60]
        queries.append(
            {"query": f"OpenClaw skill investment trading {snippet}", "label": "经验相关技能"}
        )
    return queries[:2]


def discover_skills_for_weekly(
    *,
    hot_sectors: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    experience_snippets: list[str],
    settings: Optional[dict[str, Any]] = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Search FindSkills for weekly report skill-learning section."""
    from agent_reach.daily_run.weekly_insights import SkillLearningItem

    queries = build_weekly_skill_queries(
        hot_sectors=hot_sectors,
        holdings=holdings,
        experience_snippets=experience_snippets,
    )
    if not queries:
        return [], []

    research = run_findskills_queries(queries, settings)
    items: list[SkillLearningItem] = []
    seen: set[str] = set()
    for row in research:
        for skill in row.get("skills") or []:
            title = str(skill.get("name") or skill.get("slug") or "skill")
            if title in seen:
                continue
            seen.add(title)
            items.append(
                SkillLearningItem(
                    title=title,
                    summary=str(skill.get("description") or "")[:200],
                    source=str(skill.get("source") or "findskills"),
                    url=str(skill.get("source_url") or ""),
                )
            )
    return items[:5], research
