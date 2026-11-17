#!/usr/bin/env bash
# Daily project progress — cron @ 20:00 Asia/Shanghai (fund owner Feishu).
#
# Sends a single summary card via `daily-run ops project-progress --push`.
# Requires `ops.project_progress_feishu.enabled: true` in daily_run_settings
# (shipped in `config/profiles/fund_ambush_watchlist.json`).
#
# Manual:
#   ./scripts/ops-project-progress-cron.sh
#   ./scripts/ops-project-progress-cron.sh --dry-run
#
# Cron example (daily 20:00 CST):
#   CRON_TZ=Asia/Shanghai
#   0 20 * * * /path/to/Agent-Reach/scripts/ops-project-progress-cron.sh
#
# UTC equivalent (CST = UTC+8): 50 19 * * * with TZ=Asia/Shanghai still preferred.
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
LOG_FILE="${LOG_DIR}/project-progress-$(date +%Y-%m-%d).log"

REPORT_DIR="${HOME}/.agent-reach/daily_run/reports"
mkdir -p "$REPORT_DIR"
OUTPUT="${PROJECT_PROGRESS_OUTPUT:-${REPORT_DIR}/project-progress-latest.md}"

EXTRA_ARGS=("$@")
if [ "${#EXTRA_ARGS[@]}" -eq 0 ]; then
  EXTRA_ARGS=(--push)
fi

{
  echo "=== $(date -Iseconds) project-progress pid=$$ ==="
} >>"$LOG_FILE"

cd "$REPO_ROOT"
set +e
"$PYTHON" -m agent_reach.cli daily-run ops project-progress -o "$OUTPUT" "${EXTRA_ARGS[@]}" >>"$LOG_FILE" 2>&1
ec=$?
set -e
{
  echo "=== exit=${ec} ==="
} >>"$LOG_FILE"

exit "$ec"