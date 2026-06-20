#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Reinstalling nanoleaf-kde-sync via Arch package build (pacman)..."
"${SCRIPT_DIR}/uninstall_local.sh" --migrate-pip
"${SCRIPT_DIR}/build_arch_package.sh"
