#!/usr/bin/env bash
# One-time setup: auto-login + no password prompts after boot (sudo reboot + keyring).
set -euo pipefail

USER_NAME="${SUDO_USER:-${USER:-zjk}}"
GDM_CONF="/etc/gdm3/custom.conf"
ACCOUNTS_USER="/var/lib/AccountsService/users/${USER_NAME}"
SUDOERS_REBOOT="/etc/sudoers.d/agent-reach-reboot"
POLKIT="/etc/polkit-1/rules.d/49-agent-reach-reboot.rules"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYRING_SCRIPT="${HOME}/.agent-reach/daily_run/fix-keyring-autologin.sh"
[ -x "$KEYRING_SCRIPT" ] || KEYRING_SCRIPT="${SCRIPT_DIR}/fix-keyring-autologin.sh"

if [ "$(id -u)" -ne 0 ] && [ -z "${SUDO_USER:-}" ]; then
  echo "Run once with sudo (will prompt for your password this last time):"
  echo "  sudo bash ${SCRIPT_DIR}/install-post-login-no-password.sh"
  exit 1
fi

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== 1/4 GDM auto-login for ${USER_NAME} ==="
if [ -f "$GDM_CONF" ]; then
  run_root cp -a "$GDM_CONF" "${GDM_CONF}.bak.$(date +%Y%m%d)"
  if run_root grep -q '^AutomaticLoginEnable=' "$GDM_CONF"; then
    run_root sed -i "s/^AutomaticLoginEnable=.*/AutomaticLoginEnable=true/" "$GDM_CONF"
  else
    run_root sed -i "/^\[daemon\]/a AutomaticLoginEnable=true" "$GDM_CONF"
  fi
  if run_root grep -q '^AutomaticLogin=' "$GDM_CONF"; then
    run_root sed -i "s/^AutomaticLogin=.*/AutomaticLogin=${USER_NAME}/" "$GDM_CONF"
  else
    run_root sed -i "/^AutomaticLoginEnable=true/a AutomaticLogin=${USER_NAME}" "$GDM_CONF"
  fi
  echo "✅ ${GDM_CONF}"
else
  echo "⚠️  ${GDM_CONF} not found — skip GDM autologin"
fi

echo
echo "=== 2/4 AccountsService auto-login ==="
if [ -f "$ACCOUNTS_USER" ]; then
  if run_root grep -q '^AutomaticLogin=' "$ACCOUNTS_USER"; then
    run_root sed -i 's/^AutomaticLogin=.*/AutomaticLogin=true/' "$ACCOUNTS_USER"
  else
    echo "AutomaticLogin=true" | run_root tee -a "$ACCOUNTS_USER" >/dev/null
  fi
  echo "✅ ${ACCOUNTS_USER}"
else
  echo "⚠️  ${ACCOUNTS_USER} not found — GDM config alone should suffice"
fi

echo
echo "=== 3/4 Passwordless reboot (cron / Feishu recovery) ==="
run_root tee "$SUDOERS_REBOOT" >/dev/null <<EOF
# Agent Reach daily-run: reboot without password after Feishu retry exhaustion
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl reboot, /usr/bin/systemctl reboot
${USER_NAME} ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/sbin/reboot
${USER_NAME} ALL=(ALL) NOPASSWD: /sbin/shutdown, /usr/sbin/shutdown
EOF
run_root chmod 440 "$SUDOERS_REBOOT"
run_root visudo -cf "$SUDOERS_REBOOT"

run_root tee "$POLKIT" >/dev/null <<EOF
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.login1.reboot" ||
         action.id == "org.freedesktop.login1.reboot-multiple-sessions") &&
        subject.isInGroup("sudo") && subject.user == "${USER_NAME}") {
        return polkit.Result.YES;
    }
});
EOF
echo "✅ ${SUDOERS_REBOOT}"
echo "✅ ${POLKIT}"

echo
echo "=== 4/4 Keyring (no sudo) ==="
if [ -x "$KEYRING_SCRIPT" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    su - "${USER_NAME}" -c "bash ${KEYRING_SCRIPT}" || true
  else
    bash "$KEYRING_SCRIPT" || true
  fi
fi

echo
echo "=== Verify ==="
if sudo -u "${USER_NAME}" sudo -n /bin/systemctl reboot --help >/dev/null 2>&1; then
  echo "✅ sudo -n systemctl reboot — passwordless OK"
else
  echo "⚠️  Run as ${USER_NAME}: sudo -n /bin/systemctl reboot"
fi

echo
echo "Done. Reboot once to apply auto-login + keyring changes."
echo "After reboot you should not need login or sudo passwords for reboot."
