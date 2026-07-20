#!/usr/bin/env bash
# One-time local bootstrap before enabling crontab (no GitHub Secrets required).
set -euo pipefail

AGENT_REACH_DIR="${HOME}/.agent-reach"
DAILY_RUN_DIR="${AGENT_REACH_DIR}/daily_run"
PORTFOLIO_PATH="${DAILY_RUN_DIR}/portfolio.json"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$DAILY_RUN_DIR" "${DAILY_RUN_DIR}/logs"
chmod 700 "$AGENT_REACH_DIR" "$DAILY_RUN_DIR"

if [ ! -f "${AGENT_REACH_DIR}/config.yaml" ]; then
  echo "❌ 缺少 ${AGENT_REACH_DIR}/config.yaml"
  echo "   请先运行: python3 -m agent_reach.cli setup"
  echo "   或复制 .env.example / 配置 Feishu、雪球等凭证"
  exit 1
fi

if [ ! -f "$PORTFOLIO_PATH" ]; then
  if [ -f "${REPO_ROOT}/config/daily_run_portfolio.json" ]; then
    cp "${REPO_ROOT}/config/daily_run_portfolio.json" "$PORTFOLIO_PATH"
    echo "✅ 已从 config/daily_run_portfolio.json 初始化 portfolio"
  elif [ -f "${REPO_ROOT}/config/daily_run_portfolio.example.json" ]; then
    cp "${REPO_ROOT}/config/daily_run_portfolio.example.json" "$PORTFOLIO_PATH"
    echo "✅ 已从 example 初始化 portfolio"
  else
    echo "⚠️ 未找到 portfolio 模板，请手动创建 ${PORTFOLIO_PATH}"
  fi
fi

if command -v mcporter >/dev/null 2>&1 && [ -f "${REPO_ROOT}/config/mcporter.json" ]; then
  MCPORTER_USER_DIR="${HOME}/.mcporter"
  mkdir -p "$MCPORTER_USER_DIR"
  cp "${REPO_ROOT}/config/mcporter.json" "${MCPORTER_USER_DIR}/mcporter.json"
  mcporter config add exa https://mcp.exa.ai/mcp >/dev/null 2>&1 || true
  echo "✅ mcporter 已同步"
fi

chmod +x "${REPO_ROOT}/scripts/daily-run-local-cron.sh"
echo "✅ 本地 daily-run 环境就绪"
echo "   下一步: python3 -m agent_reach.cli daily-run schedule install"
