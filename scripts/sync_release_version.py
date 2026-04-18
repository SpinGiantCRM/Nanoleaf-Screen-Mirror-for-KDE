#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
PKGBUILD_PATH = ROOT / "packaging" / "arch" / "PKGBUILD"
CHANGELOG_PATH = ROOT / "docs" / "CHANGELOG.md"

TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-(?:rc|beta|alpha)\d+)?$")


def _version_from_tag(tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag.strip())
    if not match:
        raise ValueError(
            f"Unsupported tag format '{tag}'. Expected 'vX.Y.Z' (optionally with -rcN/-betaN/-alphaN)."
        )
    return match.group("version")


def _replace_or_fail(pattern: str, replacement: str, text: str, *, path: Path) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Failed to update expected pattern '{pattern}' in {path}.")
    return updated


def sync_release_version(version: str) -> None:
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    pyproject = _replace_or_fail(r'^version = "[^"]+"$', f'version = "{version}"', pyproject, path=PYPROJECT_PATH)
    PYPROJECT_PATH.write_text(pyproject, encoding="utf-8")

    pkgbuild = PKGBUILD_PATH.read_text(encoding="utf-8")
    pkgbuild = _replace_or_fail(r"^pkgver=[^\n]+$", f"pkgver={version}", pkgbuild, path=PKGBUILD_PATH)
    PKGBUILD_PATH.write_text(pkgbuild, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    heading_pattern = re.compile(rf"^##\s+(?:\[{re.escape(version)}\]|{re.escape(version)})(?:\s|$)", flags=re.MULTILINE)
    if not heading_pattern.search(changelog):
        changelog = changelog.replace("## Unreleased\n", f"## Unreleased\n\n## {version}\n", 1)
        CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize release metadata files (pyproject, Arch PKGBUILD, changelog) from a git tag."
    )
    parser.add_argument("--git-tag", required=True, help="Git tag (for example: v1.2.3)")
    args = parser.parse_args()

    try:
        version = _version_from_tag(args.git_tag)
        sync_release_version(version)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        "Release metadata synchronized: "
        f"git_tag={args.git_tag}, version={version}, "
        f"updated=[{PYPROJECT_PATH.relative_to(ROOT)}, {PKGBUILD_PATH.relative_to(ROOT)}, {CHANGELOG_PATH.relative_to(ROOT)}]."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
