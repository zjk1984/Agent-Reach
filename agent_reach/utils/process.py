"""Subprocess helpers for consistent cross-platform text handling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

UTF8_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}

EXA_MCP_URL = "https://mcp.exa.ai/mcp"


def utf8_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces Python child processes into UTF-8 mode."""
    env = dict(base or os.environ)
    env.update(UTF8_ENV)
    return env


def mcporter_utf8_env_args() -> list[str]:
    """Return mcporter --env arguments for UTF-8 Python stdio servers."""
    args = []
    for key, value in UTF8_ENV.items():
        args.extend(["--env", f"{key}={value}"])
    return args


def bundled_mcporter_config_path() -> Path | None:
    """Resolve mcporter.json: MCPORTER_CONFIG env → repo config → user config."""
    env_path = os.environ.get("MCPORTER_CONFIG", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "config" / "mcporter.json",
        Path.cwd() / "config" / "mcporter.json",
        Path.home() / ".mcporter" / "mcporter.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def mcporter_cli_prefix() -> list[str]:
    """mcporter argv prefix with --config when a config file is available."""
    cmd = ["mcporter"]
    cfg = bundled_mcporter_config_path()
    if cfg is not None:
        cmd.extend(["--config", str(cfg)])
    return cmd
