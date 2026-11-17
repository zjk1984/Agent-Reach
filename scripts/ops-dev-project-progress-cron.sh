#!/usr/bin/env bash
# Development / coordinator project progress — cron @ 20:05 Asia/Shanghai (Feishu).
#
# Sends a single summary card via `daily-run ops dev-project-progress --push`.
# Body is read from markdown (default ~/.agent-reach/daily_run/reports/dev-project-progress.md).
# Requires `ops.dev_project_progress_feishu.enabled: true` in daily_run_settings
# (shipped in `config/profiles/fund_ambush_watchlist.json`).
#
# Chained after fund-owner ops card at 20:00 (`ops-project-progress-cron.sh`).
#
# Manual:
#   ./scripts/ops-dev-project-progress-cron.sh
#   ./scripts/ops-dev-project-progress-cron.sh --dry-run
#   DEV_PROJECT_PROGRESS_FILE=/path/to/report.md ./scripts/ops-dev-project-progress-cron.sh --push
#
# Cron example (daily 20:05 CST, after project-progress):
#   CRON_TZ=Asia/Shanghai
#   5 20 * * * /path/to/Agent-Reach/scripts/ops-dev-project-progress-cron.sh
#
set -euo pipefail

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

LOG_DIR="${HOME}/.agent-reach/daily_run/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/dev-project-progress-$(date +%Y-%m-%d).log"

EXTRA_ARGS=("$@")
if [ "${#EXTRA_ARGS[@]}" -eq 0 ]; then
  EXTRA_ARGS=(--push)
fi

FILE_ARG=()
if [ -n "${DEV_PROJECT_PROGRESS_FILE:-}" ]; then
  FILE_ARG=(--file "${DEV_PROJECT_PROGRESS_FILE}")
fi

{
  echo "=== $(date -Iseconds) dev-project-progress pid=$$ ==="
} >>"$LOG_FILE"

cd "$REPO_ROOT"
set +e
"$PYTHON" -m agent_reach.cli daily-run ops dev-project-progress "${FILE_ARG[@]}" "${EXTRA_ARGS[@]}" >>"$LOG_FILE" 2>&1
ec=$?
set -e
{
  echo "=== exit=${ec} ==="
} >>"$LOG_FILE"

exit "$ec"