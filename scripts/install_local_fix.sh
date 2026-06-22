#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "install_local_fix.sh is kept as a compatibility alias."
echo "Reinstalling via the maintained local package workflow..."
exec "${SCRIPT_DIR}/reinstall_local.sh"
