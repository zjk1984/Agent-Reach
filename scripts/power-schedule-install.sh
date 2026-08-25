#!/usr/bin/env bash
# Install local power-on/off crontab (Asia/Shanghai).
#
# Schedule (boot via rtcwake at prior shutdown):
#   Every day: 00:00 off → wake 06:25 same day
#   (Noon 12:00 lunch shutdown removed — daily-run midday at 12:30 stays in daily-run cron)
#
# Also run once: sudo bash scripts/install-power-schedule-sudo.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/power-schedule.sh"
MARKER_BEGIN="# agent-reach power-schedule BEGIN"
MARKER_END="# agent-reach power-schedule END"

chmod +x "$SCRIPT" "${REPO_ROOT}/scripts/install-power-schedule-sudo.sh"

BLOCK=$(cat <<EOF
${MARKER_BEGIN}
SHELL=/bin/bash
CRON_TZ=Asia/Shanghai
# log: ~/.agent-reach/daily_run/logs/power-schedule-YYYY-MM-DD.log
# script: ${SCRIPT}
0 0 * * * ${SCRIPT} midnight  # 00:00 off → wake 06:25 every day
${MARKER_END}
EOF
)

if ! command -v crontab >/dev/null 2>&1; then
  OUT="${HOME}/.agent-reach/daily_run/crontab-power-schedule.txt"
  mkdir -p "$(dirname "$OUT")"
  printf '%s\n' "$BLOCK" >"$OUT"
  echo "❌ crontab not found; wrote ${OUT} — install manually"
  exit 1
fi

existing="$(crontab -l 2>/dev/null || true)"
before=""
after=""
if echo "$existing" | grep -qF "$MARKER_BEGIN"; then
  before="$(echo "$existing" | sed "/${MARKER_BEGIN}/,/${MARKER_END}/d" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}')"
  after=""
fi

new_crontab="$before"
[ -n "$new_crontab" ] && new_crontab="${new_crontab}"$'\n'
new_crontab="${new_crontab}${BLOCK}"
[ -n "$after" ] && new_crontab="${new_crontab}"$'\n'"${after}"

printf '%s\n' "$new_crontab" | crontab -

echo "✅ Power schedule crontab installed (Asia/Shanghai)"
echo "   Every day: 00:00 off → rtcwake 06:25 same day"
echo "   Boot time uses rtcwake at shutdown"
echo
echo "⚠️  Run once if not done: sudo bash ${REPO_ROOT}/scripts/install-power-schedule-sudo.sh"
echo "⚠️  KVM/VM: if rtcwake does not wake the guest, configure host VM autostart at those times"
