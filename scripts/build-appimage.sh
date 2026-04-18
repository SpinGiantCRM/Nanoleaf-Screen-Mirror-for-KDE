#!/usr/bin/env bash
set -euo pipefail

APP_NAME="nanoleaf-kde-sync"
APPIMAGE_NAME="${APP_NAME}.AppImage"
APPIMAGETOOL_VERSION="13"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="df3baf5ca5facbecfc2f3fa6713c29ab9cefa8fd8c1eac5d283b79cab33e4acb"
PYTHON_VERSION="3.11"
PYTHON_BIN="python${PYTHON_VERSION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_ROOT="$REPO_ROOT/build/appimage"
APPDIR="$BUILD_ROOT/AppDir"
DIST_DIR="$REPO_ROOT/dist"
OUTPUT_PATH="$REPO_ROOT/$APPIMAGE_NAME"
VERIFY_ONLY=0

download_and_verify_appimagetool() {
  local tool_path="$1"

  curl -L --fail "$APPIMAGETOOL_URL" -o "$tool_path"

  local actual_sha
  actual_sha="$(sha256sum "$tool_path" | awk '{print $1}')"
  if [[ "$actual_sha" != "$APPIMAGETOOL_SHA256" ]]; then
    echo "Error: appimagetool SHA256 mismatch."
    echo "Expected: $APPIMAGETOOL_SHA256"
    echo "Actual:   $actual_sha"
    exit 1
  fi

  chmod +x "$tool_path"
}

if [[ "${1:-}" == "--verify-appimagetool" ]]; then
  VERIFY_ONLY=1
elif [[ "${1:-}" != "" ]]; then
  echo "Usage: $0 [--verify-appimagetool]"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required to download appimagetool."
  exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "Error: sha256sum is required to verify appimagetool."
  exit 1
fi

mkdir -p "$BUILD_ROOT"
APPIMAGE_TOOL="$BUILD_ROOT/appimagetool.AppImage"
download_and_verify_appimagetool "$APPIMAGE_TOOL"

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  echo "appimagetool ${APPIMAGETOOL_VERSION} downloaded and verified successfully."
  exit 0
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: $PYTHON_BIN is required to build this AppImage."
  echo "This AppImage currently expects a matching $PYTHON_BIN runtime on the target system."
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/python${PYTHON_VERSION}/site-packages"

"$PYTHON_BIN" -m pip install --upgrade pip build
"$PYTHON_BIN" -m build --wheel

"$PYTHON_BIN" -m pip install --no-compile --target "$APPDIR/usr/lib/python${PYTHON_VERSION}/site-packages" "$DIST_DIR"/*.whl

cat > "$APPDIR/usr/bin/$APP_NAME" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$HERE/usr/lib/python3.11/site-packages:${PYTHONPATH:-}"
exec python3.11 -m nanoleaf_sync.ui.tray "$@"
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
