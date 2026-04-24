#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
AUTOSTART_FILE="${HOME}/.config/autostart/${APP_NAME}.desktop"
SYSTEMD_UNIT="${HOME}/.config/systemd/user/${APP_NAME}.service"
DESKTOP_ENTRY="${HOME}/.local/share/applications/${APP_NAME}.desktop"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
CACHE_DIR="${HOME}/.cache/${APP_NAME}"

echo "Stopping running ${APP_NAME} processes (if any)..."
pkill -f "${APP_NAME}-service" 2>/dev/null || true
pkill -f "${APP_NAME}$" 2>/dev/null || true

if command -v "${APP_NAME}-autostart" >/dev/null 2>&1; then
  "${APP_NAME}-autostart" disable --method desktop || true
  "${APP_NAME}-autostart" disable --method systemd || true
fi

echo "Removing local integration files..."
rm -f "${AUTOSTART_FILE}" "${SYSTEMD_UNIT}" "${DESKTOP_ENTRY}"

echo "Uninstalling Python package from user site-packages..."
python -m pip uninstall -y "${APP_NAME}" >/dev/null 2>&1 || true

if [[ "${1:-}" == "--purge-config" ]]; then
  echo "Purging config/cache..."
  rm -rf "${CONFIG_DIR}" "${CACHE_DIR}"
fi

echo "Done."
