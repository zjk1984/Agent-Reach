#!/usr/bin/env bash
# Map Asia/Shanghai wall clock (or workflow_dispatch input) to daily-run job name.
set -euo pipefail

if [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ]; then
  job="${INPUT_JOB:-intraday}"
  echo "job=${job}"
  echo "skip=false"
  exit 0
fi

h=$(TZ=Asia/Shanghai date +%H)
m=$(TZ=Asia/Shanghai date +%M)
h=$((10#$h))
m=$((10#$m))
minutes=$((h * 60 + m))

# Morning window ~08:00 CST (allow GitHub schedule delay).
if [ "$minutes" -ge 470 ] && [ "$minutes" -le 520 ]; then
  echo "job=morning"
  echo "skip=false"
  exit 0
fi

# Close window ~15:30 CST.
if [ "$minutes" -ge 920 ] && [ "$minutes" -le 965 ]; then
  echo "job=close"
  echo "skip=false"
  exit 0
fi

# Intraday scans ~09:25–15:05 CST.
if [ "$minutes" -ge 565 ] && [ "$minutes" -le 905 ]; then
  echo "job=intraday"
  echo "skip=false"
  exit 0
fi

echo "job=intraday"
echo "skip=true"
