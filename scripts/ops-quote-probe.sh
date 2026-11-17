#!/usr/bin/env bash
# Weekday 06:55 CST quote probe — WARN-only; runs after ops-trading-day-precheck (06:50).
#
# Probes a small set of holding + watchlist codes via D1 quote_fetch; stale/missing
# are WARN + optional Feishu, never exit 1 (does not block morning).
#
# Manual:
#   ./scripts/ops-quote-probe.sh
#   ./scripts/ops-quote-probe.sh --json
#
# Cron (after precheck):
#   55 6 * * 1-5 cd /path/to/Agent-Reach && ./scripts/ops-quote-probe.sh >> ~/.agent-reach/daily_run/logs/quote-probe-$(date +\%F).log 2>&1
#
set -uo pipefail

export TZ="${TZ:-Asia/Shanghai}"
export PYTHONUNBUFFERED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export AGENT_REACH_REPO_ROOT="${REPO_ROOT}"

PYTHON="${DAILY_RUN_PYTHON:-}"
if [ -z "$PYTHON" ] && [ -x "${REPO_ROOT}/venv/bin/python3" ]; then
  PYTHON="${REPO_ROOT}/venv/bin/python3"
else
  PYTHON="${PYTHON:-python3}"
fi
export PATH="${HOME}/.local/bin:${HOME}/.local/node/bin:${PATH}"

ENV_FILE="${HOME}/.agent-reach/config.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

cd "$REPO_ROOT"
exec "$PYTHON" -m agent_reach.daily_run.ops_quote_probe "$@"