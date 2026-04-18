#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
APPIMAGE_NAME="${APP_NAME}.AppImage"
APPIMAGETOOL_CHANNEL="continuous"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_CHANNEL}/appimagetool-x86_64.AppImage"
PYTHON_STANDALONE_FLAVOR="cpython-3.11.8+20240224-x86_64-unknown-linux-gnu-install_only.tar.gz"
PYTHON_STANDALONE_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.11.8%2B20240224-x86_64-unknown-linux-gnu-install_only.tar.gz"
PYTHON_STANDALONE_SHA256="94e13d0e5ad417035b80580f3e893a72e094b0900d5d64e7e34ab08e95439987"
PYTHON_STANDALONE_VERSION="3.11"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_ROOT="${REPO_ROOT}/build/appimage"
APPDIR="${BUILD_ROOT}/AppDir"
DIST_DIR="${REPO_ROOT}/dist"
APPIMAGE_TOOL="${BUILD_ROOT}/appimagetool.AppImage"
PYTHON_ARCHIVE_PATH="${BUILD_ROOT}/${PYTHON_STANDALONE_FLAVOR}"
OUTPUT_PATH="${REPO_ROOT}/${APPIMAGE_NAME}"
VERIFY_ONLY=0

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: missing required command '$cmd'." >&2
    exit 1
  fi
}

check_sha256() {
  local file_path="$1"
  local expected="$2"
  local label="$3"

  local actual
  actual="$(sha256sum "$file_path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "Error: ${label} SHA256 mismatch." >&2
    echo "Expected: $expected" >&2
    echo "Actual:   $actual" >&2
    exit 1
  fi
}

download_file() {
  local url="$1"
  local out="$2"
  curl --retry 5 --retry-all-errors --retry-delay 2 -fsSL "$url" -o "$out"
}

download_toolchain() {
  mkdir -p "$BUILD_ROOT"

  download_file "$APPIMAGETOOL_URL" "$APPIMAGE_TOOL"
  chmod +x "$APPIMAGE_TOOL"

  download_file "$PYTHON_STANDALONE_URL" "$PYTHON_ARCHIVE_PATH"
  check_sha256 "$PYTHON_ARCHIVE_PATH" "$PYTHON_STANDALONE_SHA256" "standalone CPython archive"
}

verify_appimagetool() {
  if ! "$APPIMAGE_TOOL" --appimage-version >/dev/null 2>&1; then
    echo "Error: downloaded appimagetool failed to execute." >&2
    exit 1
  fi
}

write_launcher() {
  cat > "${APPDIR}/usr/bin/${APP_NAME}" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_ROOT="\$HERE/usr/python"
export PYTHONHOME="\$PYTHON_ROOT"
export PYTHONPATH="\$PYTHON_ROOT/lib/python${PYTHON_STANDALONE_VERSION}/site-packages\${PYTHONPATH:+:\$PYTHONPATH}"
export LD_LIBRARY_PATH="\$PYTHON_ROOT/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "\$PYTHON_ROOT/bin/python3" -m nanoleaf_sync.ui.tray "\$@"
LAUNCHER
  chmod +x "${APPDIR}/usr/bin/${APP_NAME}"
}

write_apprun() {
  cat > "${APPDIR}/AppRun" <<'APPRUN'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/usr/bin/nanoleaf-kde-sync" "$@"
APPRUN
  chmod +x "${APPDIR}/AppRun"
}

write_icon() {
  cat > "${APPDIR}/nanoleaf-kde-sync.svg" <<'SVG'
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

build_wheel_into_bundled_python() {
  local pybin="${APPDIR}/usr/python/bin/python3"
  if [[ ! -x "$pybin" ]]; then
    echo "Error: bundled Python executable missing at ${pybin}." >&2
    exit 1
  fi

  "$pybin" -m ensurepip --upgrade
  "$pybin" -m pip install --upgrade pip build

  cd "$REPO_ROOT"
  "$pybin" -m build --wheel
  if ! compgen -G "${DIST_DIR}/*.whl" >/dev/null; then
    echo "Error: no wheel built in ${DIST_DIR}." >&2
    exit 1
  fi
  "$pybin" -m pip install --no-compile "${DIST_DIR}"/*.whl
}

parse_args() {
  case "${1:-}" in
    "") return ;;
    --verify-appimagetool) VERIFY_ONLY=1 ;;
    *)
      echo "Usage: $0 [--verify-appimagetool]" >&2
      exit 1
      ;;
  esac
}

main() {
  parse_args "${1:-}"

  require_cmd curl
  require_cmd sha256sum
  require_cmd tar
  require_cmd python3

  download_toolchain
  verify_appimagetool

  if [[ "$VERIFY_ONLY" -eq 1 ]]; then
    echo "appimagetool (${APPIMAGETOOL_CHANNEL}) and ${PYTHON_STANDALONE_FLAVOR} downloaded and verified successfully."
    return
  fi

  rm -rf "$BUILD_ROOT"
  mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/python"
  download_toolchain

  tar -xzf "$PYTHON_ARCHIVE_PATH" -C "${APPDIR}/usr/python" --strip-components=1
  build_wheel_into_bundled_python
  write_launcher
  write_apprun
  cp "$REPO_ROOT/docs/nanoleaf-kde-sync.desktop" "${APPDIR}/nanoleaf-kde-sync.desktop"
  write_icon

  ARCH=x86_64 "$APPIMAGE_TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT_PATH"
  chmod +x "$OUTPUT_PATH"

  echo "Built AppImage at: ${OUTPUT_PATH}"
}

main "$@"
