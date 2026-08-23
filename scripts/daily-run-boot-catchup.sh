#!/usr/bin/env bash
# After reboot, catch up missed 07:00 premarket S1 when the machine wakes late.
#
# Invoked from user crontab:
#   @reboot sleep 60 && ./scripts/daily-run-boot-catchup.sh
#
# Manual:
#   ./scripts/daily-run-boot-catchup.sh
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
LOG_FILE="${LOG_DIR}/boot-catchup-$(date +%Y-%m-%d).log"

ENV_FILE="${HOME}/.agent-reach/config.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [ ! -f "${HOME}/.agent-reach/config.yaml" ]; then
  {
    echo "=== $(date -Iseconds) ERROR ==="
    echo "missing ~/.agent-reach/config.yaml"
  } >>"$LOG_FILE"
  exit 1
fi

{
  echo "=== $(date -Iseconds) boot-catchup pid=$$ ==="
  cd "$REPO_ROOT"
  "$PYTHON" - <<'PY'
import json
from agent_reach.daily_run.schedule import run_boot_catchup

print(json.dumps(run_boot_catchup(), ensure_ascii=False, indent=2))
PY
  echo "=== exit=$? ==="
} >>"$LOG_FILE" 2>&1
