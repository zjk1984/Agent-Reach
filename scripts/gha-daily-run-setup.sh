#!/usr/bin/env bash
# Bootstrap ~/.agent-reach for GitHub Actions daily-run jobs.
#
# Portfolio seeding (only when portfolio.json is missing, or RESET_PORTFOLIO=true):
#   1. AGENT_REACH_PORTFOLIO_JSON secret (optional)
#   2. config/daily_run_portfolio.json in repo (commit your baseline here)
#   3. config/daily_run_portfolio.example.json
#
# After the first seed, GHA cache keeps portfolio.json — no secret update needed
# for day-to-day paper trades or watchlist changes.
set -euo pipefail

AGENT_REACH_DIR="${HOME}/.agent-reach"
DAILY_RUN_DIR="${AGENT_REACH_DIR}/daily_run"
PORTFOLIO_PATH="${DAILY_RUN_DIR}/portfolio.json"
mkdir -p "$DAILY_RUN_DIR"
chmod 700 "$AGENT_REACH_DIR" "$DAILY_RUN_DIR"

if [ -n "${AGENT_REACH_CONFIG_YAML:-}" ]; then
  printf '%s\n' "$AGENT_REACH_CONFIG_YAML" > "${AGENT_REACH_DIR}/config.yaml"
  chmod 600 "${AGENT_REACH_DIR}/config.yaml"
elif [ ! -f "${AGENT_REACH_DIR}/config.yaml" ]; then
  echo "Missing AGENT_REACH_CONFIG_YAML secret (Feishu / 雪球 / Twitter 等凭证)" >&2
  exit 1
fi

reset_portfolio="${RESET_PORTFOLIO:-false}"
if [ "$reset_portfolio" = "true" ] && [ -f "$PORTFOLIO_PATH" ]; then
  rm -f "$PORTFOLIO_PATH"
  echo "RESET_PORTFOLIO=true — removed cached portfolio.json for re-seed"
fi

if [ ! -f "$PORTFOLIO_PATH" ]; then
  if [ -n "${AGENT_REACH_PORTFOLIO_JSON:-}" ]; then
    printf '%s\n' "$AGENT_REACH_PORTFOLIO_JSON" > "$PORTFOLIO_PATH"
    echo "Seeded portfolio.json from AGENT_REACH_PORTFOLIO_JSON secret"
  elif [ -f config/daily_run_portfolio.json ]; then
    cp config/daily_run_portfolio.json "$PORTFOLIO_PATH"
    echo "Seeded portfolio.json from config/daily_run_portfolio.json (repo)"
  else
    cp config/daily_run_portfolio.example.json "$PORTFOLIO_PATH"
    echo "Seeded portfolio.json from config/daily_run_portfolio.example.json"
  fi
else
  echo "Using existing portfolio.json (cache or prior run)"
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
  MCPORTER_USER_DIR="${HOME}/.mcporter"
  mkdir -p "$MCPORTER_USER_DIR"
  if [ -f config/mcporter.json ]; then
    cp config/mcporter.json "${MCPORTER_USER_DIR}/mcporter.json"
    echo "Synced config/mcporter.json → ${MCPORTER_USER_DIR}/mcporter.json"
  fi
  mcporter config add exa https://mcp.exa.ai/mcp >/dev/null 2>&1 || true
fi

export MCPORTER_CONFIG="${MCPORTER_CONFIG:-${GITHUB_WORKSPACE:-$(pwd)}/config/mcporter.json}"

echo "Agent Reach GHA setup OK: config + portfolio ready under ${AGENT_REACH_DIR}"
