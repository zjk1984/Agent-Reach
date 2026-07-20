#!/usr/bin/env bash
# 本地 crontab 触发 daily-run（直接跑 CLI，不经过 GitHub Actions）
#
# 推荐安装方式（一次性）：
#   bash scripts/daily-run-local-setup.sh
#   python3 -m agent_reach.cli daily-run schedule install
#
# 手动单 job：
#   ./scripts/daily-run-local-cron.sh morning

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/daily-run-local-cron.sh" "${1:-intraday}"
