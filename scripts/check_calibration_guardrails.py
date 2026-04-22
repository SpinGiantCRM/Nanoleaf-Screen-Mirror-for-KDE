#!/usr/bin/env python3
"""Guardrail checks for calibration parity and test discipline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CALIBRATION_LOGIC_PATHS = {
    "src/nanoleaf_sync/color/zone_mapper.py",
    "src/nanoleaf_sync/runtime/anchor_calibration.py",
    "src/nanoleaf_sync/runtime/calibration_resolver.py",
    "src/nanoleaf_sync/ui/calibration_flow.py",
    "src/nanoleaf_sync/ui/display_configurator.py",
    "src/nanoleaf_sync/ui/zone_calibration.py",
}

INTEGRATION_TEST_PATHS = {
    "tests/test_pipeline_integration.py",
    "tests/test_display_configurator.py",
    "tests/test_wizard_and_settings_structure.py",
}

SCHEMA_MODEL_PATHS = {
    "src/nanoleaf_sync/config/model.py",
    "src/nanoleaf_sync/config/serialization.py",
}

REQUIRED_SYNC_PATHS = {
    "docs/CALIBRATION_PARITY_SPEC.md",
    "docs/CALIBRATION_PARITY_TEST_CHECKLIST.md",
    "VERSION",
}


def _changed_files(base_ref: str, head_ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _validate_paths_exist(paths: set[str]) -> list[str]:
    missing = []
    for path in sorted(paths):
        if not Path(path).exists():
            missing.append(path)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail PR validation when calibration guardrails are not satisfied.",
    )
    parser.add_argument("--base", required=True, help="Base git ref (e.g. origin/main)")
    parser.add_argument("--head", required=True, help="Head git ref (e.g. HEAD)")
    args = parser.parse_args()

    changed = _changed_files(args.base, args.head)
    failures: list[str] = []

    if changed & CALIBRATION_LOGIC_PATHS and not (changed & INTEGRATION_TEST_PATHS):
        failures.append(
            "Calibration mapping/wizard logic changed without an integration test update. "
            f"Update at least one of: {', '.join(sorted(INTEGRATION_TEST_PATHS))}."
        )

    if changed & SCHEMA_MODEL_PATHS:
        missing_sync_updates = sorted(REQUIRED_SYNC_PATHS - changed)
        if missing_sync_updates:
            failures.append(
                "Schema/model files changed without required parity sync updates. "
                "Also update: "
                + ", ".join(missing_sync_updates)
                + "."
            )

    missing_expected_files = _validate_paths_exist(REQUIRED_SYNC_PATHS)
    if missing_expected_files:
        failures.append(
            "Guardrail check expects these files to exist but they are missing: "
            + ", ".join(missing_expected_files)
            + "."
        )

    if failures:
        print("Calibration guardrail check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Calibration guardrail check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
