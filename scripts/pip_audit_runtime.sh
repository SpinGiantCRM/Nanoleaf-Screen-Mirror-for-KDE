#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$(mktemp -d)"
trap 'rm -rf "${VENV_DIR}"' EXIT

cd "${ROOT_DIR}"

python -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
pip install .
pip-audit
