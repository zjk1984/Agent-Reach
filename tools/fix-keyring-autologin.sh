#!/usr/bin/env bash
# Reset GNOME login keyring so auto-login does not prompt for a password.
# Safe to run without sudo. Re-run after changing your Linux login password.
set -euo pipefail

KEYRING_DIR="${HOME}/.local/share/keyrings"
BACKUP_DIR="${KEYRING_DIR}/backup-$(date +%Y%m%d-%H%M%S)"

if [ ! -d "$KEYRING_DIR" ]; then
  echo "No keyring directory — nothing to fix."
  exit 0
fi

mkdir -p "$BACKUP_DIR"
shopt -s nullglob
for f in "$KEYRING_DIR"/*.keyring "$KEYRING_DIR"/user.keystore; do
  [ -e "$f" ] || continue
  mv "$f" "$BACKUP_DIR/"
  echo "Backed up: $(basename "$f")"
done
shopt -u nullglob

killall gnome-keyring-daemon 2>/dev/null || true

echo
echo "✅ Keyring reset. Backup: ${BACKUP_DIR}"
echo
echo "Next step: log out and let auto-login bring you back."
echo "If GNOME asks for a new keyring password, leave it EMPTY and continue."
echo "After that, you should not see keyring prompts on boot."
