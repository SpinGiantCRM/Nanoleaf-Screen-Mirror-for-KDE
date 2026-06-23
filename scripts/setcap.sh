#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-/usr/bin/nanoleaf_drm_helper}"

if [ ! -x "${TARGET}" ]; then
  echo "DRM helper not found or not executable: ${TARGET}" >&2
  exit 1
fi

if ! command -v setcap >/dev/null 2>&1; then
  echo "setcap not available; install libcap" >&2
  exit 1
fi

setcap cap_sys_admin,cap_sys_ptrace+ep "${TARGET}"
getcap "${TARGET}"
