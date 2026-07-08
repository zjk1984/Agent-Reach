#!/usr/bin/env bash
# Upload Agent Reach config to GitHub Actions secrets (run locally with admin gh auth).
set -euo pipefail

REPO="${1:-}"
CONFIG="${AGENT_REACH_CONFIG:-${HOME}/.agent-reach/config.yaml}"
PORTFOLIO="${AGENT_REACH_PORTFOLIO:-${HOME}/.agent-reach/daily_run/portfolio.json}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Install GitHub CLI: https://cli.github.com/" >&2
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "Missing config: $CONFIG" >&2
  exit 1
fi

if [ -n "$REPO" ]; then
  GH_REPO=(--repo "$REPO")
else
  GH_REPO=()
fi

echo "Setting AGENT_REACH_CONFIG_YAML from $CONFIG ..."
gh secret set AGENT_REACH_CONFIG_YAML "${GH_REPO[@]}" < "$CONFIG"

if [ -f "$PORTFOLIO" ]; then
  echo "Setting AGENT_REACH_PORTFOLIO_JSON from $PORTFOLIO ..."
  gh secret set AGENT_REACH_PORTFOLIO_JSON "${GH_REPO[@]}" < "$PORTFOLIO"
else
  echo "Skip AGENT_REACH_PORTFOLIO_JSON (file not found: $PORTFOLIO)"
fi

echo "Done. Verify: gh secret list ${GH_REPO[*]}"
echo "Test run: gh workflow run daily-run-schedule.yml ${GH_REPO[*]} -f job=morning -f dry_run=true"
