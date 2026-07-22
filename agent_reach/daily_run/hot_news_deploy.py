# -*- coding: utf-8
"""Self-hosted 60s API deployment (Docker) for daily-run hot news."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run")

CONTAINER_NAME = "agent-reach-60s"
IMAGE = "vikiboss/60s:latest"
HOST_PORT = 8787
CONTAINER_PORT = 4399
LOCAL_BASE_URL = f"http://127.0.0.1:{HOST_PORT}"


def docker_path() -> Optional[str]:
    return shutil.which("docker")


def container_running(name: str = CONTAINER_NAME) -> bool:
    docker = docker_path()
    if not docker:
        return False
    try:
        out = subprocess.run(
            [docker, "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return name in (out.stdout or "").strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return False


def container_exists(name: str = CONTAINER_NAME) -> bool:
    docker = docker_path()
    if not docker:
        return False
    try:
        out = subprocess.run(
            [docker, "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return name in (out.stdout or "").strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_local_base_url(base_urls: Optional[list[str]] = None, *, timeout: int = 5) -> Optional[str]:
    from agent_reach.daily_run.hot_news_collector import _resolve_base_url

    urls = base_urls or [LOCAL_BASE_URL]
    return _resolve_base_url(urls, timeout=timeout)


def merge_user_hot_news_settings(
    *,
    base_urls: Optional[list[str]] = None,
    path: Optional[Path] = None,
) -> Path:
    """Ensure ~/.agent-reach/daily_run_settings.json prefers local 60s."""
    from agent_reach.daily_run.settings import _DEFAULT_PATH, _read_json, clear_settings_cache

    out = path or (Path.home() / ".agent-reach" / "daily_run_settings.json")
    if out.exists():
        cfg = _read_json(out)
    elif _DEFAULT_PATH.exists():
        cfg = _read_json(_DEFAULT_PATH)
    else:
        cfg = {}

    hot = dict(cfg.get("hot_news") or {})
    hot.setdefault("enabled", True)
    preferred = base_urls or [LOCAL_BASE_URL, "https://60s.viki.moe"]
    hot["base_urls"] = preferred
    hot["deploy"] = {
        "mode": "docker",
        "container_name": CONTAINER_NAME,
        "image": IMAGE,
        "host_port": HOST_PORT,
        "container_port": CONTAINER_PORT,
        "local_base_url": LOCAL_BASE_URL,
    }
    cfg["hot_news"] = hot

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_settings_cache()
    return out


def pull_image(*, image: str = IMAGE) -> tuple[bool, str]:
    docker = docker_path()
    if not docker:
        return False, "docker not found on PATH"
    try:
        proc = subprocess.run(
            [docker, "pull", image],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, err or f"docker pull failed ({proc.returncode})"
        return True, f"pulled {image}"
    except subprocess.TimeoutExpired:
        return False, "docker pull timed out"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def start_container(*, force: bool = False, pull: bool = True) -> tuple[bool, str]:
    docker = docker_path()
    if not docker:
        return False, "docker not found on PATH"

    if container_running():
        return True, f"container {CONTAINER_NAME} already running"

    if pull:
        ok, msg = pull_image()
        if not ok:
            logger.debug("60s image pull skipped/failed: {}", msg)

    if container_exists() and not force:
        try:
            proc = subprocess.run(
                [docker, "start", CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode == 0:
                return True, f"started existing container {CONTAINER_NAME}"
            err = (proc.stderr or proc.stdout or "").strip()
            return False, err or "docker start failed"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)

    if container_exists() and force:
        subprocess.run([docker, "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=30, check=False)

    cmd = [
        docker,
        "run",
        "-d",
        "--restart",
        "unless-stopped",
        "--name",
        CONTAINER_NAME,
        "-p",
        f"{HOST_PORT}:{CONTAINER_PORT}",
        IMAGE,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, err or "docker run failed"
        return True, f"created container {CONTAINER_NAME} on {LOCAL_BASE_URL}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def stop_container(*, remove: bool = False) -> tuple[bool, str]:
    docker = docker_path()
    if not docker:
        return False, "docker not found on PATH"
    if not container_exists():
        return True, "container not present"
    try:
        subprocess.run([docker, "stop", CONTAINER_NAME], capture_output=True, text=True, timeout=60, check=False)
        if remove:
            subprocess.run([docker, "rm", CONTAINER_NAME], capture_output=True, text=True, timeout=30, check=False)
            return True, f"removed container {CONTAINER_NAME}"
        return True, f"stopped container {CONTAINER_NAME}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def wait_healthy(*, timeout: int = 60, poll_interval: float = 2.0) -> tuple[bool, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        base = resolve_local_base_url([LOCAL_BASE_URL], timeout=3)
        if base:
            return True, base
        time.sleep(poll_interval)
    return False, f"60s API not reachable at {LOCAL_BASE_URL} within {timeout}s"


def install_60s_local(
    *,
    pull: bool = True,
    force: bool = False,
    skip_docker: bool = False,
    wait_timeout: int = 60,
) -> dict[str, Any]:
    """Deploy local 60s via Docker and merge user hot_news settings."""
    result: dict[str, Any] = {
        "ok": False,
        "local_base_url": LOCAL_BASE_URL,
        "container_name": CONTAINER_NAME,
        "image": IMAGE,
        "docker": bool(docker_path()),
        "running": container_running(),
        "reachable": False,
        "settings_path": None,
        "message": "",
    }

    settings_path = merge_user_hot_news_settings()
    result["settings_path"] = str(settings_path)

    if skip_docker:
        base = resolve_local_base_url([LOCAL_BASE_URL, "https://60s.viki.moe"])
        result["reachable"] = base == LOCAL_BASE_URL
        result["active_base_url"] = base
        result["ok"] = bool(base)
        result["message"] = "docker skipped; using existing endpoint or public fallback"
        return result

    if not docker_path():
        base = resolve_local_base_url([LOCAL_BASE_URL, "https://60s.viki.moe"])
        result["active_base_url"] = base
        result["ok"] = bool(base)
        result["message"] = (
            "docker not available; hot_news will use public fallback https://60s.viki.moe"
            if base != LOCAL_BASE_URL
            else "local 60s already reachable without docker"
        )
        return result

    if resolve_local_base_url([LOCAL_BASE_URL], timeout=3) and not force:
        result["running"] = container_running()
        result["reachable"] = True
        result["active_base_url"] = LOCAL_BASE_URL
        result["ok"] = True
        result["message"] = f"local 60s already healthy at {LOCAL_BASE_URL}"
        return result

    ok, msg = start_container(force=force, pull=pull)
    result["running"] = container_running()
    if not ok:
        base = resolve_local_base_url([LOCAL_BASE_URL, "https://60s.viki.moe"])
        result["active_base_url"] = base
        result["ok"] = bool(base)
        result["message"] = f"docker deploy failed: {msg}"
        return result

    healthy, health_msg = wait_healthy(timeout=wait_timeout)
    result["reachable"] = healthy
    result["active_base_url"] = health_msg if healthy else resolve_local_base_url(
        [LOCAL_BASE_URL, "https://60s.viki.moe"]
    )
    result["ok"] = healthy or bool(result["active_base_url"])
    result["message"] = health_msg if healthy else f"deployed but health check failed: {health_msg}"
    return result


def status_60s() -> dict[str, Any]:
    """Report local 60s container and API reachability."""
    from agent_reach.daily_run.settings import load_settings

    cfg = load_settings()
    hot = cfg.get("hot_news") or {}
    base_urls = list(hot.get("base_urls") or [LOCAL_BASE_URL, "https://60s.viki.moe"])
    active = resolve_local_base_url(base_urls)
    local_ok = resolve_local_base_url([LOCAL_BASE_URL]) == LOCAL_BASE_URL

    return {
        "docker": bool(docker_path()),
        "container_name": CONTAINER_NAME,
        "container_running": container_running(),
        "local_base_url": LOCAL_BASE_URL,
        "local_reachable": local_ok,
        "active_base_url": active,
        "using_public_fallback": active == "https://60s.viki.moe" and not local_ok,
        "base_urls": base_urls,
        "platforms": hot.get("platforms"),
    }
