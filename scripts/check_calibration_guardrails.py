#!/usr/bin/env python3
"""Lightweight CI guardrail checks for calibration-related changes.

This script is intentionally conservative:
- If git metadata is unavailable, it exits successfully.
- If no calibration/runtime files changed, it exits successfully.
- If calibration/runtime files changed, it requires at least one matching test file
  to be changed in the same range.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

CALIBRATION_PATH_PREFIXES = (
    "src/nanoleaf_sync/ui/calibration",
    "src/nanoleaf_sync/runtime/calibration",
    "src/nanoleaf_sync/runtime/anchor_calibration.py",
    "src/nanoleaf_sync/runtime/zone_derivation.py",
    "src/nanoleaf_sync/runtime/zones.py",
)

TEST_HINT_PREFIXES = (
    "tests/test_calibration",
    "tests/test_corner_anchor_calibration.py",
    "tests/test_zone_calibration.py",
    "tests/test_zone_derivation.py",
    "tests/test_runtime_zones.py",
)


def _git_changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base git revision")
    parser.add_argument("--head", required=True, help="Head git revision")
    args = parser.parse_args()

    if not Path(".git").exists():
        print("Calibration guardrails skipped: .git metadata not present.")
        return 0

    try:
        changed_files = _git_changed_files(args.base, args.head)
    except Exception as exc:  # pragma: no cover - defensive CI behavior
        print(f"Calibration guardrails skipped: {exc}")
        return 0

    calibration_changes = [
        file_path
        for file_path in changed_files
        if _matches_prefix(file_path, CALIBRATION_PATH_PREFIXES)
    ]
    if not calibration_changes:
        print("Calibration guardrails passed: no calibration/runtime calibration files changed.")
        return 0

    has_related_tests = any(
        _matches_prefix(file_path, TEST_HINT_PREFIXES) for file_path in changed_files
    )
    if has_related_tests:
        print("Calibration guardrails passed: calibration changes include related test updates.")
        return 0

    print("Calibration guardrails failed.", file=sys.stderr)
    print("Calibration-related files changed without updating related tests:", file=sys.stderr)
    for file_path in calibration_changes:
        print(f"  - {file_path}", file=sys.stderr)
    print("Please update calibration-related tests in the same pull request.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
