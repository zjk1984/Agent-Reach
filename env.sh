# Agent Reach 环境配置 - 使用前 source 此文件
# source /home/zjk/cursor/env.sh

export AGENT_REACH_HOME="/home/zjk/cursor"

# Node.js (包含 npm/npx)
export PATH="$AGENT_REACH_HOME/tools/node-v22.14.0-linux-x64/bin:$PATH"

# gh CLI
export PATH="$AGENT_REACH_HOME/tools/gh_2.70.0_linux_amd64/bin:$PATH"

# Python venv
export PATH="$AGENT_REACH_HOME/venv/bin:$PATH"

# mcporter config
export MCPORTER_CONFIG="$AGENT_REACH_HOME/tools/config/mcporter.json"

# 时区
export TZ="Asia/Shanghai"

echo "Agent Reach 环境已加载"
echo "  agent-reach  $(agent-reach --version 2>/dev/null)"
echo "  node         $(node --version 2>/dev/null)"
echo "  npm          $(npm --version 2>/dev/null)"
echo "  gh           $(gh --version 2>/dev/null | head -1)"
echo "  mcporter     $(which mcporter 2>/dev/null)"
