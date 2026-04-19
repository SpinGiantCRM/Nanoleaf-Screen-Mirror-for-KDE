#!/usr/bin/env python3
"""Sync CHANGELOG.md with GitHub release notes for a published version."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def normalize_release_notes(notes: str) -> str:
    lines = [line.rstrip() for line in notes.strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Release version in X.Y.Z format")
    parser.add_argument("--notes", required=True, help="Release notes markdown text")
    parser.add_argument("--release-date", default=date.today().isoformat())
    args = parser.parse_args()

    version = args.version.strip()
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"ERROR: version must be X.Y.Z, got {version!r}")

    notes = normalize_release_notes(args.notes)
    if not notes:
        raise SystemExit("ERROR: release notes were empty; refusing to write placeholder changelog entry")

    release_date = args.release_date.strip()
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    if f"## [{version}]" in changelog:
        print(f"CHANGELOG already contains {version}; nothing to do.")
        return

    marker = "## [Unreleased]"
    idx = changelog.find(marker)
    if idx == -1:
        raise SystemExit("ERROR: CHANGELOG.md is missing '## [Unreleased]' heading")

    insert_at = idx + len(marker)
    insertion = f"\n\n## [{version}] - {release_date}\n\n{notes}"
    updated = changelog[:insert_at] + insertion + changelog[insert_at:]
    CHANGELOG_PATH.write_text(updated, encoding="utf-8")
    print(f"Inserted changelog section for {version}.")


if __name__ == "__main__":
    main()
