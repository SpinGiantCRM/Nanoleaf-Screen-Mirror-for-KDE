#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
WHEEL_AUDIT_DIR="$(mktemp -d)"
trap 'rm -rf "${WHEEL_AUDIT_DIR}"' EXIT

python scripts/check_release_versions.py
python scripts/verify_runtime_install.py
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent
bandit -r src/ -c pyproject.toml
pip-audit --path .
bash scripts/build_drm_helper.sh
python -m build --wheel --no-isolation --outdir "${WHEEL_AUDIT_DIR}"
python scripts/validate_wheel.py "${WHEEL_AUDIT_DIR}"/*-linux_x86_64.whl
python -m pytest -q --timeout=60 --timeout-method=thread --durations=25 \
  --cov=nanoleaf_sync --cov-report=term-missing --cov-fail-under=75

echo "Release gate passed."
