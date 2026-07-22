#!/usr/bin/env bash
# Deploy self-hosted 60s API (native Node.js by default) for daily-run hot news.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=false
SKIP_DEPLOY=false
NO_PULL=false
MODE="native"

usage() {
  cat <<'EOF'
Usage: scripts/60s-local-setup.sh [--mode native|docker|auto] [--force] [--skip-deploy] [--no-pull]

  --mode native   Node.js 本机进程（默认，无需 Docker）
  --mode docker   Docker 容器部署
  --mode auto     先 native，失败再 docker
  --force         强制重建进程/容器
  --skip-deploy   仅写入 hot_news 配置，不启动 60s
  --no-pull       跳过 git pull / docker pull
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=true ;;
    --skip-deploy|--skip-docker) SKIP_DEPLOY=true ;;
    --no-pull) NO_PULL=true ;;
    --mode) MODE="${2:?}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
  shift
done

ARGS=(python3 -m agent_reach.cli daily-run hot-news install --mode "$MODE")
if [ "$FORCE" = true ]; then
  ARGS+=(--force)
fi
if [ "$SKIP_DEPLOY" = true ]; then
  ARGS+=(--skip-deploy)
fi
if [ "$NO_PULL" = true ]; then
  ARGS+=(--no-pull)
fi

cd "$REPO_ROOT"
"${ARGS[@]}"
