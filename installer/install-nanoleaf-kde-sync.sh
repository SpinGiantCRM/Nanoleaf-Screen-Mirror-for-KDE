#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
APPIMAGE_NAME="nanoleaf-kde-sync.AppImage"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ICON_SRC="$REPO_ROOT/assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg"
UDEV_RULE_SRC="$REPO_ROOT/assets/udev/60-nanoleaf-kde-sync.rules"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
APPIMAGE_DST="$INSTALL_DIR/$APPIMAGE_NAME"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/$APP_NAME.desktop"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"
CONFIG_FILE="$CONFIG_DIR/config.json"

print_step() {
  echo
  echo "==> $1"
}

find_priv_helper() {
  if command -v pkexec >/dev/null 2>&1; then
    echo "pkexec"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    echo "sudo"
    return
  fi
  echo ""
}

install_udev_rule() {
  if [[ ! -f "$UDEV_RULE_SRC" ]]; then
    echo "udev rule source not found at $UDEV_RULE_SRC"
    return 1
  fi

  local helper
  helper="$(find_priv_helper)"
  if [[ -z "$helper" ]]; then
    echo "Couldn't find pkexec or sudo to install USB permissions rule."
    echo "You can still use Demo mode now and set up USB permissions later."
    return 0
  fi

  print_step "Setting up USB permissions (udev rule)"
  echo "You'll be asked for administrator approval once."

  if [[ "$helper" == "pkexec" ]]; then
    pkexec install -Dm0644 "$UDEV_RULE_SRC" /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
    pkexec udevadm control --reload-rules || true
    pkexec udevadm trigger --subsystem-match=hidraw || true
  else
    sudo install -Dm0644 "$UDEV_RULE_SRC" /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
    sudo udevadm control --reload-rules || true
    sudo udevadm trigger --subsystem-match=hidraw || true
  fi

  echo "USB permissions installed. If your Nanoleaf was already plugged in, unplug/replug it."
}

write_default_config() {
  mkdir -p "$CONFIG_DIR"
  if [[ -f "$CONFIG_FILE" ]]; then
    return
  fi
  cat > "$CONFIG_FILE" <<'JSON'
{
  "allow_capture_fallback": true,
  "brightness": 0.7,
  "device_pid": 33282,
  "device_vid": 14330,
  "fps": 30,
  "prefer_backend": "kwin-dbus",
  "replay_frames_path": "",
  "smoothing": 0.2,
  "use_mock_capture": true,
  "use_mock_device": true,
  "zones": [
    {
      "h": 1.0,
      "w": 1.0,
      "x": 0.0,
      "y": 0.0
    }
  ]
}
JSON
}

install_desktop_file() {
  mkdir -p "$DESKTOP_DIR"
  cat > "$DESKTOP_FILE" <<EOF_DESKTOP
[Desktop Entry]
Type=Application
Name=nanoleaf-kde-sync
Comment=Nanoleaf ambient light sync for KDE/Linux
Exec=$APPIMAGE_DST
Icon=nanoleaf-kde-sync
Terminal=false
Categories=System;Utility;
X-KDE-StartupNotify=false
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOF_DESKTOP

  mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
  install -m 0644 "$ICON_SRC" "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
  fi
}

main() {
  local appimage_src="${1:-}"
  if [[ -z "$appimage_src" ]]; then
    appimage_src="$SCRIPT_DIR/$APPIMAGE_NAME"
  fi

  if [[ ! -f "$appimage_src" ]]; then
    echo "Could not find AppImage: $appimage_src"
    echo "Usage: $0 /path/to/nanoleaf-kde-sync.AppImage"
    exit 1
  fi

  if [[ ! -f "$ICON_SRC" ]]; then
    echo "Missing icon file: $ICON_SRC"
    exit 1
  fi

  print_step "Installing nanoleaf-kde-sync"
  mkdir -p "$INSTALL_DIR"
  install -m 0755 "$appimage_src" "$APPIMAGE_DST"

  print_step "Creating app launcher"
  install_desktop_file

  print_step "Preparing first-run settings"
  write_default_config

  install_udev_rule

  print_step "Done"
  echo "nanoleaf-kde-sync is now in your KDE launcher menu."
  echo "If your USB strip was plugged in already, unplug/replug once."

  print_step "Launching app"
  nohup "$APPIMAGE_DST" >/dev/null 2>&1 &
}

main "$@"
