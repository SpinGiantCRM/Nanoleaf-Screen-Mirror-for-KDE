#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
APPIMAGE_NAME="${APP_NAME}.AppImage"
APPIMAGETOOL_VERSION="13"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="df3baf5ca5facbecfc2f3fa6713c29ab9cefa8fd8c1eac5d283b79cab33e4acb"
PYTHON_STANDALONE_FLAVOR="cpython-3.11.8+20240224-x86_64-unknown-linux-gnu-install_only.tar.gz"
PYTHON_STANDALONE_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.11.8%2B20240224-x86_64-unknown-linux-gnu-install_only.tar.gz"
PYTHON_STANDALONE_SHA256="94e13d0e5ad417035b80580f3e893a72e094b0900d5d64e7e34ab08e95439987"
PYTHON_STANDALONE_VERSION="3.11"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_ROOT="$REPO_ROOT/build/appimage"
APPDIR="$BUILD_ROOT/AppDir"
DIST_DIR="$REPO_ROOT/dist"
OUTPUT_PATH="$REPO_ROOT/$APPIMAGE_NAME"
VERIFY_ONLY=0

check_sha256() {
  local file_path="$1"
  local expected_sha="$2"
  local label="$3"

  local actual_sha
  actual_sha="$(sha256sum "$file_path" | awk '{print $1}')"
  if [[ "$actual_sha" != "$expected_sha" ]]; then
    echo "Error: ${label} SHA256 mismatch."
    echo "Expected: $expected_sha"
    echo "Actual:   $actual_sha"
    exit 1
  fi
}

download_and_verify_appimagetool() {
  local tool_path="$1"

  curl -L --fail "$APPIMAGETOOL_URL" -o "$tool_path"
  check_sha256 "$tool_path" "$APPIMAGETOOL_SHA256" "appimagetool"
  chmod +x "$tool_path"
}

download_and_verify_standalone_python() {
  local archive_path="$1"

  curl -L --fail "$PYTHON_STANDALONE_URL" -o "$archive_path"
  check_sha256 "$archive_path" "$PYTHON_STANDALONE_SHA256" "standalone CPython archive"
}

if [[ "${1:-}" == "--verify-appimagetool" ]]; then
  VERIFY_ONLY=1
elif [[ "${1:-}" != "" ]]; then
  echo "Usage: $0 [--verify-appimagetool]"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required to download pinned AppImage toolchain artifacts."
  exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "Error: sha256sum is required to verify downloaded release tooling."
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo "Error: tar is required to extract the standalone CPython archive."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required to orchestrate the AppImage build steps."
  exit 1
fi

mkdir -p "$BUILD_ROOT"
APPIMAGE_TOOL="$BUILD_ROOT/appimagetool.AppImage"
PYTHON_ARCHIVE_PATH="$BUILD_ROOT/${PYTHON_STANDALONE_FLAVOR}"

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  download_and_verify_appimagetool "$APPIMAGE_TOOL"
  download_and_verify_standalone_python "$PYTHON_ARCHIVE_PATH"
  echo "appimagetool ${APPIMAGETOOL_VERSION} and ${PYTHON_STANDALONE_FLAVOR} downloaded and verified successfully."
  exit 0
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/python"

download_and_verify_appimagetool "$APPIMAGE_TOOL"
download_and_verify_standalone_python "$PYTHON_ARCHIVE_PATH"

# python-build-standalone archives contain a top-level directory. Strip it to place
# the relocatable tree directly at AppDir/usr/python.
tar -xzf "$PYTHON_ARCHIVE_PATH" -C "$APPDIR/usr/python" --strip-components=1

BUNDLED_PYTHON_BIN="$APPDIR/usr/python/bin/python3"
if [[ ! -x "$BUNDLED_PYTHON_BIN" ]]; then
  echo "Error: bundled Python executable not found at $BUNDLED_PYTHON_BIN after extraction."
  exit 1
fi

"$BUNDLED_PYTHON_BIN" -m ensurepip --upgrade
"$BUNDLED_PYTHON_BIN" -m pip install --upgrade pip build
"$BUNDLED_PYTHON_BIN" -m build --wheel
"$BUNDLED_PYTHON_BIN" -m pip install --no-compile "$DIST_DIR"/*.whl

cat > "$APPDIR/usr/bin/$APP_NAME" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_ROOT="\$HERE/usr/python"
export PYTHONHOME="\$PYTHON_ROOT"
export PYTHONPATH="\$PYTHON_ROOT/lib/python${PYTHON_STANDALONE_VERSION}/site-packages\${PYTHONPATH:+:\$PYTHONPATH}"
export LD_LIBRARY_PATH="\$PYTHON_ROOT/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "\$PYTHON_ROOT/bin/python3" -m nanoleaf_sync.ui.tray "\$@"
LAUNCHER
chmod +x "$APPDIR/usr/bin/$APP_NAME"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/usr/bin/nanoleaf-kde-sync" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

cp "$REPO_ROOT/docs/nanoleaf-kde-sync.desktop" "$APPDIR/nanoleaf-kde-sync.desktop"
cat > "$APPDIR/nanoleaf-kde-sync.svg" <<'SVG'
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

ARCH=x86_64 "$APPIMAGE_TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT_PATH"
chmod +x "$OUTPUT_PATH"

echo "Built AppImage at: $OUTPUT_PATH"
