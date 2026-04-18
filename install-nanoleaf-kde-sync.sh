#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
APPIMAGE_NAME="nanoleaf-kde-sync.AppImage"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
APPIMAGE_DST="$INSTALL_DIR/$APPIMAGE_NAME"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/$APP_NAME.desktop"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
ICON_DST="$ICON_DIR/$APP_NAME.svg"
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

write_embedded_icon() {
  mkdir -p "$ICON_DIR"
  cat > "$ICON_DST" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="nanoleaf-kde-sync">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3ddc97"/>
      <stop offset="1" stop-color="#30a7ff"/>
    </linearGradient>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="24" fill="#20242f"/>
  <path d="M26 90L58 34c2-4 8-4 10 0l32 56c2 4-1 8-5 8H31c-4 0-7-4-5-8z" fill="url(#g)"/>
  <circle cx="64" cy="74" r="10" fill="#ffffff" opacity="0.9"/>
</svg>
SVG
}

install_udev_rule() {
  local helper
  helper="$(find_priv_helper)"
  if [[ -z "$helper" ]]; then
    echo "Couldn't find pkexec or sudo to install USB permissions rule."
    echo "You can still use Demo mode now and set up USB permissions later."
    return 0
  fi

  local temp_rule
  temp_rule="$(mktemp)"
  trap 'rm -f "$temp_rule"' RETURN

  cat > "$temp_rule" <<'RULES'
# Nanoleaf USB Screen Mirror Light Strip and Pegboard Desk Dock
# Gives local users access via the `plugdev` group.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="37fa", ATTRS{idProduct}=="8201", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="37fa", ATTRS{idProduct}=="8202", MODE="0660", GROUP="plugdev", TAG+="uaccess"
RULES

  print_step "Setting up USB permissions (udev rule)"
  echo "You'll be asked for administrator approval once."

  if [[ "$helper" == "pkexec" ]]; then
    pkexec install -Dm0644 "$temp_rule" /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
    pkexec udevadm control --reload-rules || true
    pkexec udevadm trigger --subsystem-match=hidraw || true
  else
    sudo install -Dm0644 "$temp_rule" /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
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

  write_embedded_icon

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
