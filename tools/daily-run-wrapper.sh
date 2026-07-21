#!/usr/bin/env bash
# Agent Reach daily-run wrapper for cron
# Sets up all environment variables needed by agent-reach daily-run.
set -euo pipefail

export HOME="/home/zjk"
export TZ="Asia/Shanghai"
export PATH="/home/zjk/cursor/venv/bin:/home/zjk/cursor/tools/node-v22.14.0-linux-x64/bin:/home/zjk/cursor/tools/gh_2.70.0_linux_amd64/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export MCPORTER_CONFIG="/home/zjk/cursor/tools/config/mcporter.json"

exec /home/zjk/cursor/venv/bin/agent-reach "$@"
