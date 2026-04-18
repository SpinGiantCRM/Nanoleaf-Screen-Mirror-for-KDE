#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="$SCRIPT_DIR/../assets/udev/60-nanoleaf-kde-sync.rules"
RULE_DST="/etc/udev/rules.d/60-nanoleaf-kde-sync.rules"

if [[ ! -f "$RULE_SRC" ]]; then
  echo "Missing udev rule source file: $RULE_SRC" >&2
  exit 1
fi

echo "Installing udev rule to $RULE_DST"
sudo install -m 0644 "$RULE_SRC" "$RULE_DST"

echo "Reloading udev rules"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

echo
cat <<'EOF'
Done.
Reconnect your Nanoleaf USB device, then verify permissions:
  ls -l /dev/hidraw*
  getfacl /dev/hidrawX   # replace X with your device node

If your user is not in plugdev, add it and relogin:
  sudo usermod -aG plugdev "$USER"
EOF
