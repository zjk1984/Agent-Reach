#!/usr/bin/env bash
# Quant PM weekly digest — cron @ 09:30 Asia/Shanghai Saturdays (after weekly ~08:30).
#
# Builds markdown + optional Feishu summary card (distinct from multi-card weekly push).
# Documented in AGENTS.md (Quant PM weekly digest).
#
# Manual:
#   ./scripts/ops-quant-digest-cron.sh
#
# Cron example (Saturday 09:30 CST):
#   CRON_TZ=Asia/Shanghai
#   30 9 * * 6 /path/to/Agent-Reach/scripts/ops-quant-digest-cron.sh
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
LOG_FILE="${LOG_DIR}/quant-digest-$(date +%Y-%m-%d).log"

REPORT_DIR="${HOME}/.agent-reach/daily_run/reports"
mkdir -p "$REPORT_DIR"
OUTPUT="${QUANT_DIGEST_OUTPUT:-${REPORT_DIR}/quant-digest-latest.md}"

{
  echo "=== $(date -Iseconds) quant-digest pid=$$ ==="
} >>"$LOG_FILE"

cd "$REPO_ROOT"
set +e
"$PYTHON" -m agent_reach.cli daily-run ops quant-digest -o "$OUTPUT" --push >>"$LOG_FILE" 2>&1
ec=$?
set -e
{
  echo "=== exit=${ec} ==="
} >>"$LOG_FILE"

exit "$ec"
