#!/usr/bin/env bash
# Deploy self-hosted 60s API (Docker) for daily-run hot news.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=false
SKIP_DOCKER=false
NO_PULL=false

usage() {
  cat <<'EOF'
Usage: scripts/60s-local-setup.sh [--force] [--skip-docker] [--no-pull]

  --force        Recreate Docker container even if one exists
  --skip-docker  Only merge hot_news settings; do not start Docker
  --no-pull      Skip docker pull before run
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=true ;;
    --skip-docker) SKIP_DOCKER=true ;;
    --no-pull) NO_PULL=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
  shift
done

ARGS=(python3 -m agent_reach.cli daily-run hot-news install)
if [ "$FORCE" = true ]; then
  ARGS+=(--force)
fi
if [ "$SKIP_DOCKER" = true ]; then
  ARGS+=(--skip-docker)
fi
if [ "$NO_PULL" = true ]; then
  ARGS+=(--no-pull)
fi

cd "$REPO_ROOT"
"${ARGS[@]}"
