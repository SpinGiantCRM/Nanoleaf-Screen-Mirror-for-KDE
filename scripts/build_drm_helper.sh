#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/src/nanoleaf_sync/capture/_drm_helper.c"
OUT="${ROOT}/src/nanoleaf_sync/capture/nanoleaf_drm_helper"

cc -O2 -Wall -Wextra -o "${OUT}" "${SRC}"
chmod +x "${OUT}"
echo "Built ${OUT}"
echo "Optional: sudo setcap cap_sys_admin,cap_sys_ptrace+ep ${OUT}"
