#!/usr/bin/env bash
# Map 北京时间 wall clock (or workflow_dispatch / cron schedule) to daily-run job name.
set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"

if [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ]; then
  job="${INPUT_JOB:-intraday}"
  echo "job=${job}"
  echo "skip=false"
  exit 0
fi

# Prefer the cron expression that triggered this run (GitHub Actions timezone-aware schedule).
if [ -n "${GITHUB_EVENT_SCHEDULE:-}" ]; then
  case "${GITHUB_EVENT_SCHEDULE}" in
    "10 8 * * 1-5")
      echo "job=morning"
      echo "skip=false"
      exit 0
      ;;
    "30 15 * * 1-5")
      echo "job=close"
      echo "skip=false"
      exit 0
      ;;
    "0 7 * * 1-5"|"0 8 * * 1-5"|\
    "30 9 * * 1-5"|"0 10 * * 1-5"|"30 10 * * 1-5"|"0 11 * * 1-5"|"30 11 * * 1-5"|\
    "0 13 * * 1-5"|"30 13 * * 1-5"|"0 14 * * 1-5"|"30 14 * * 1-5"|"0 15 * * 1-5")
      echo "job=intraday"
      echo "skip=false"
      exit 0
      ;;
  esac
fi

h=$(date +%H)
m=$(date +%M)
h=$((10#$h))
m=$((10#$m))
minutes=$((h * 60 + m))

# Morning window ~08:10 北京时间 (allow GitHub schedule delay).
if [ "$minutes" -ge 485 ] && [ "$minutes" -le 535 ]; then
  echo "job=morning"
  echo "skip=false"
  exit 0
fi

# Close window ~15:30 北京时间.
if [ "$minutes" -ge 920 ] && [ "$minutes" -le 965 ]; then
  echo "job=close"
  echo "skip=false"
  exit 0
fi

# Premarket intraday scans ~07:00–08:15 北京时间.
if [ "$minutes" -ge 410 ] && [ "$minutes" -le 495 ]; then
  echo "job=intraday"
  echo "skip=false"
  exit 0
fi

# Intraday scans ~09:25–15:05 北京时间.
if [ "$minutes" -ge 565 ] && [ "$minutes" -le 905 ]; then
  echo "job=intraday"
  echo "skip=false"
  exit 0
fi

echo "job=intraday"
echo "skip=true"
