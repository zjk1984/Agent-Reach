#!/usr/bin/env bash
# 本地 crontab 触发 daily-run（fork 仓库 GHA schedule 默认不跑时使用）
#
# 安装示例（北京时间，工作日）：
#   crontab -e
#   0 7 * * 1-5  /path/to/dispatch-daily-run-local-cron.sh intraday >>/tmp/daily-run-cron.log 2>&1
#   0 8 * * 1-5  /path/to/dispatch-daily-run-local-cron.sh morning >>/tmp/daily-run-cron.log 2>&1
#
# 需要：gh auth login 且对 zjk1984/Agent-Reach 有 workflow 权限

set -euo pipefail

JOB="${1:-intraday}"
REPO="${DAILY_RUN_REPO:-zjk1984/Agent-Reach}"
WORKFLOW="${DAILY_RUN_WORKFLOW:-daily-run-schedule.yml}"

export TZ=Asia/Shanghai

if ! command -v gh >/dev/null 2>&1; then
  echo "需要 GitHub CLI: https://cli.github.com/" >&2
  exit 1
fi

echo "[$(date -Iseconds)] dispatch job=${JOB} repo=${REPO}"
gh workflow run "$WORKFLOW" \
  --repo "$REPO" \
  -f "job=${JOB}" \
  -f "dry_run=false"

echo "已触发 workflow_dispatch；在 Actions 页查看运行状态。"
