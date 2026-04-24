#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Reinstalling nanoleaf-kde-sync from local checkout..."
"${SCRIPT_DIR}/uninstall_local.sh"

cd "${ROOT_DIR}"
python -m pip install --user --upgrade .

echo "Refreshing local launcher entry..."
python -c "from nanoleaf_sync.desktop_entry import ensure_user_launcher_entry; print(ensure_user_launcher_entry())"

echo "If needed, reinstall udev rules with: ./scripts/setup_udev.sh"
echo "Done."
