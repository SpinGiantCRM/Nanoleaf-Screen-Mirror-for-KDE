#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARCH_DIR="${ROOT_DIR}/packaging/arch"
PKGVER="$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION")"
PKGREL="$(awk -F= '/^pkgrel=/{print $2}' "${ARCH_DIR}/PKGBUILD")"
SRC_DIR="Nanoleaf-Screen-Mirror-for-KDE-${PKGVER}"
TARBALL="${ARCH_DIR}/nanoleaf-kde-sync-${PKGVER}.tar.gz"

check_no_runtime_processes() {
  local matches
  matches="$(pgrep -af '(^|[ /])nanoleaf-kde-sync(-service)?($|[ ])|nanoleaf_sync\.ui\.tray_app' || true)"
  if [[ -n "${matches}" ]]; then
    echo "Refusing to build/install while nanoleaf-kde-sync appears to be running:"
    echo "${matches}"
    echo "Stop the tray/service from the app or systemd, then rerun this script."
    exit 1
  fi
}

echo "Checking for running nanoleaf-kde-sync processes..."
check_no_runtime_processes

echo "Building source tarball ${TARBALL}..."
rm -f "${TARBALL}"
(
  cd "${ROOT_DIR}"
  git ls-files -z | tar --null -T - -czf "${TARBALL}" \
    --transform "s|^|${SRC_DIR}/|"
)

echo "Building and installing Arch package (pkgver=${PKGVER})..."
cd "${ARCH_DIR}"
if ! makepkg -si --noconfirm --skipchecksums; then
  echo ""
  echo "If pacman install failed (sudo password required), install the built package manually:"
  echo "  sudo pacman -U ${ARCH_DIR}/nanoleaf-kde-sync-${PKGVER}-${PKGREL}-$(uname -m).pkg.tar.zst"
  exit 1
fi

echo "Installed $(pacman -Q nanoleaf-kde-sync 2>/dev/null || echo 'nanoleaf-kde-sync (query failed)')"
echo "Launcher: $(command -v nanoleaf-kde-sync || echo 'not found')"
python "${SCRIPT_DIR}/verify_runtime_install.py"
echo "If needed, reinstall udev rules with: ${ROOT_DIR}/scripts/setup_udev.sh"
