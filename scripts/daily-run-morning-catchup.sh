#!/usr/bin/env bash
# One-shot 08:05 morning retry when 08:00 manifest is FAIL or incomplete (playbook L1-B).
#
# Cron (CRON_TZ=Asia/Shanghai, weekdays):
#   5 8 * * 1-5 /path/to/Agent-Reach/scripts/daily-run-morning-catchup.sh
#
# Manual:
#   ./scripts/daily-run-morning-catchup.sh
set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"
export PYTHONUNBUFFERED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${DAILY_RUN_PYTHON:-}"
if [ -z "$PYTHON" ] && [ -x "${REPO_ROOT}/venv/bin/python3" ]; then
  PYTHON="${REPO_ROOT}/venv/bin/python3"
else
  PYTHON="${PYTHON:-python3}"
fi

LOG_DIR="${HOME}/.agent-reach/daily_run/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/morning-catchup-$(date +%Y-%m-%d).log"

ENV_FILE="${HOME}/.agent-reach/config.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

{
  echo "=== $(date -Iseconds) morning-catchup pid=$$ ==="
  cd "$REPO_ROOT"
  "$PYTHON" -m agent_reach.daily_run.morning_catchup
  echo "=== exit=$? ==="
} >>"$LOG_FILE" 2>&1