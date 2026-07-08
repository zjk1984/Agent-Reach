#!/usr/bin/env bash
# Bootstrap ~/.agent-reach for GitHub Actions daily-run jobs.
set -euo pipefail

AGENT_REACH_DIR="${HOME}/.agent-reach"
DAILY_RUN_DIR="${AGENT_REACH_DIR}/daily_run"
mkdir -p "$DAILY_RUN_DIR"
chmod 700 "$AGENT_REACH_DIR" "$DAILY_RUN_DIR"

if [ -n "${AGENT_REACH_CONFIG_YAML:-}" ]; then
  printf '%s\n' "$AGENT_REACH_CONFIG_YAML" > "${AGENT_REACH_DIR}/config.yaml"
  chmod 600 "${AGENT_REACH_DIR}/config.yaml"
elif [ ! -f "${AGENT_REACH_DIR}/config.yaml" ]; then
  echo "Missing AGENT_REACH_CONFIG_YAML secret (Feishu / 雪球 / Twitter 等凭证)" >&2
  exit 1
fi

if [ -n "${AGENT_REACH_PORTFOLIO_JSON:-}" ]; then
  printf '%s\n' "$AGENT_REACH_PORTFOLIO_JSON" > "${DAILY_RUN_DIR}/portfolio.json"
elif [ ! -f "${DAILY_RUN_DIR}/portfolio.json" ]; then
  cp config/daily_run_portfolio.example.json "${DAILY_RUN_DIR}/portfolio.json"
fi

# Export Twitter creds for twitter-cli (optional, from config.yaml).
eval "$(python3 - <<'PY'
import os, shlex
from pathlib import Path
try:
    import yaml
except ImportError:
    raise SystemExit(0)
path = Path.home() / ".agent-reach" / "config.yaml"
if not path.is_file():
    raise SystemExit(0)
data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
token = data.get("twitter_auth_token") or ""
ct0 = data.get("twitter_ct0") or ""
if token and ct0:
    print(f"export TWITTER_AUTH_TOKEN={shlex.quote(str(token))}")
    print(f"export TWITTER_CT0={shlex.quote(str(ct0))}")
PY
)"

if command -v mcporter >/dev/null 2>&1; then
  mcporter config add exa https://mcp.exa.ai/mcp >/dev/null 2>&1 || true
fi

echo "Agent Reach GHA setup OK: config + portfolio ready under ${AGENT_REACH_DIR}"
