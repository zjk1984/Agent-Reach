#!/usr/bin/env bash
# Trading-day ops precheck — run before the open (cron @ 06:50 Asia/Shanghai weekdays).
#
# Checks: git main vs origin/main, pip editable install, job_health close/morning,
# doctor quick smoke, disk space, optional Cursor worker note.
#
# Documented in AGENTS.md (Ops / fund-owner autopilot Phase A).
#
# Manual:
#   ./scripts/ops-trading-day-precheck.sh
#   ./scripts/ops-trading-day-precheck.sh --json
#
# Cron example (weekday 06:50 CST):
#   50 6 * * 1-5 cd /path/to/Agent-Reach && ./scripts/ops-trading-day-precheck.sh >> ~/.agent-reach/daily_run/logs/precheck-$(date +\%F).log 2>&1
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
exec "$PYTHON" -m agent_reach.daily_run.ops_trading_day_precheck "$@"
