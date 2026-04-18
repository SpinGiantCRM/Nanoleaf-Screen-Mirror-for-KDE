#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_NAME="60-nanoleaf-kde-sync.rules"
RULE_SRC="${SCRIPT_DIR}/../assets/udev/${RULE_NAME}"
RULE_DST="/etc/udev/rules.d/${RULE_NAME}"

require_root_tools() {
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Error: sudo is required for udev rule installation." >&2
    exit 1
  fi
  if ! command -v udevadm >/dev/null 2>&1; then
    echo "Error: udevadm is required for reloading udev rules." >&2
    exit 1
  fi
}

install_rule() {
  if [[ ! -f "$RULE_SRC" ]]; then
    echo "Error: missing udev rule source file: ${RULE_SRC}" >&2
    exit 1
  fi

  echo "Installing ${RULE_NAME} -> ${RULE_DST}"
  sudo install -m 0644 "$RULE_SRC" "$RULE_DST"
}

reload_rules() {
  echo "Reloading udev rules and retriggering hidraw devices"
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw
}

print_next_steps() {
  cat <<'EOF'
Done.
Reconnect your Nanoleaf USB device, then verify permissions:
  ls -l /dev/hidraw*
  getfacl /dev/hidrawX   # replace X with your device node

If your user is not in plugdev, add it and relogin:
  sudo usermod -aG plugdev "$USER"
EOF
}

main() {
  require_root_tools
  install_rule
  reload_rules
  echo
  print_next_steps
}

main "$@"
