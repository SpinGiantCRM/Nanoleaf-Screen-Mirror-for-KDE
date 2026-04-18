#!/usr/bin/env python3
"""Synchronize release version metadata from an annotated git tag."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
PKGBUILD_PATH = ROOT / "packaging" / "arch" / "PKGBUILD"
CHANGELOG_PATH = ROOT / "docs" / "CHANGELOG.md"
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-(?:rc|beta|alpha)\d+)?$")


@dataclass(frozen=True)
class SyncResult:
    version: str
    changelog_created: bool


def _version_from_tag(tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag.strip())
    if not match:
        raise ValueError(
            f"Unsupported tag format '{tag}'. Expected 'vX.Y.Z' (optionally with -rcN/-betaN/-alphaN)."
        )
    return match.group("version")


def _replace_single(pattern: str, replacement: str, text: str, path: Path) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Expected to replace exactly one pattern '{pattern}' in {path}.")
    return updated


def _sync_pyproject(version: str) -> None:
    contents = PYPROJECT_PATH.read_text(encoding="utf-8")
    updated = _replace_single(r'^version = "[^"]+"$', f'version = "{version}"', contents, PYPROJECT_PATH)
    PYPROJECT_PATH.write_text(updated, encoding="utf-8")


def _sync_pkgbuild(version: str) -> None:
    contents = PKGBUILD_PATH.read_text(encoding="utf-8")
    updated = _replace_single(r"^pkgver=[^\n]+$", f"pkgver={version}", contents, PKGBUILD_PATH)
    PKGBUILD_PATH.write_text(updated, encoding="utf-8")


def _sync_changelog(version: str) -> bool:
    contents = CHANGELOG_PATH.read_text(encoding="utf-8")
    has_heading = re.search(
        rf"^##\s+(?:\[{re.escape(version)}\]|{re.escape(version)})(?:\s|$)",
        contents,
        flags=re.MULTILINE,
    )
    if has_heading:
        return False

    marker = "## Unreleased\n"
    if marker not in contents:
        raise RuntimeError(f"Expected '{marker.strip()}' heading in {CHANGELOG_PATH}.")

    updated = contents.replace(marker, f"{marker}\n## {version}\n", 1)
    CHANGELOG_PATH.write_text(updated, encoding="utf-8")
    return True


def sync_release_version(version: str) -> SyncResult:
    _sync_pyproject(version)
    _sync_pkgbuild(version)
    created = _sync_changelog(version)
    return SyncResult(version=version, changelog_created=created)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync pyproject, Arch PKGBUILD, and changelog release metadata from a tag."
    )
    parser.add_argument("--git-tag", required=True, help="Example: v1.2.3 or v1.2.3-rc1")
    args = parser.parse_args()

    try:
        version = _version_from_tag(args.git_tag)
        result = sync_release_version(version)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Release metadata synchronized: "
        f"git_tag={args.git_tag}, version={result.version}, changelog_created={result.changelog_created}, "
        f"updated=[{PYPROJECT_PATH.relative_to(ROOT)}, {PKGBUILD_PATH.relative_to(ROOT)}, {CHANGELOG_PATH.relative_to(ROOT)}]."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
