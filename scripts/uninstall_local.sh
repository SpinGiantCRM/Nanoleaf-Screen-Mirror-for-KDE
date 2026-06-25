#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
AUTOSTART_FILE="${HOME}/.config/autostart/${APP_NAME}.desktop"
SYSTEMD_UNIT="${HOME}/.config/systemd/user/${APP_NAME}.service"
DESKTOP_ENTRY="${HOME}/.local/share/applications/${APP_NAME}.desktop"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
CACHE_DIR="${HOME}/.cache/${APP_NAME}"

matches="$(pgrep -af '(^|[ /])nanoleaf-kde-sync(-service)?($|[ ])|nanoleaf_sync\.ui\.tray_app' || true)"
if [[ -n "${matches}" ]]; then
  echo "Refusing to uninstall while ${APP_NAME} appears to be running:"
  echo "${matches}"
  echo "Stop the tray/service from the app or systemd, then rerun this script."
  exit 1
fi

if command -v "${APP_NAME}-autostart" >/dev/null 2>&1; then
  "${APP_NAME}-autostart" disable --method desktop || true
  "${APP_NAME}-autostart" disable --method systemd || true
fi

echo "Removing user launcher/autostart integration files..."
rm -f "${AUTOSTART_FILE}" "${SYSTEMD_UNIT}" "${DESKTOP_ENTRY}"

if [[ "${1:-}" == "--migrate-pip" || "${1:-}" == "--purge-config" ]]; then
  echo "Removing legacy pip user install (if present)..."
  python -m pip uninstall -y "${APP_NAME}" >/dev/null 2>&1 || true
fi

if [[ "${1:-}" == "--purge-config" ]]; then
  echo "Purging config/cache..."
  rm -rf "${CONFIG_DIR}" "${CACHE_DIR}"
fi

echo "Done."
