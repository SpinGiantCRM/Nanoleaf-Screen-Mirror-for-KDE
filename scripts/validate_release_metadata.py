#!/usr/bin/env python3
"""Validate project release metadata consistency."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ in CI
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
CHANGELOG_PATH = ROOT / "docs" / "CHANGELOG.md"
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


class ValidationError(Exception):
    """Raised when release metadata validation fails."""


def _read_project_version() -> str:
    with PYPROJECT_PATH.open("rb") as handle:
        pyproject = tomllib.load(handle)

    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise ValidationError(
            f"{PYPROJECT_PATH} is missing a [project] table. Expected project.version to be defined."
        )

    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValidationError(
            f"{PYPROJECT_PATH} has an invalid project.version value. Expected a non-empty string like 1.2.3."
        )

    return version.strip()


def _changelog_has_version(version: str) -> bool:
    # Matches headings such as "## 1.2.3" and "## [1.2.3]".
    header_pattern = re.compile(
        rf"^##\s+(?:\[{re.escape(version)}\]|{re.escape(version)})(?:\s|$)",
        re.MULTILINE,
    )
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    return header_pattern.search(text) is not None


def _validate_tag(tag: str, version: str) -> None:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValidationError(
            "Git tag format mismatch: "
            f"got '{tag}', expected format 'vX.Y.Z' (for example 'v{version}')."
        )

    tag_version = match.group("version")
    if tag_version != version:
        raise ValidationError(
            "Git tag version mismatch: "
            f"pyproject.toml has '{version}', but git tag '{tag}' points to '{tag_version}'. "
            f"Expected tag 'v{version}'."
        )


def validate_release_metadata(tag: str | None) -> None:
    version = _read_project_version()

    if not _changelog_has_version(version):
        raise ValidationError(
            "Changelog section missing: "
            f"docs/CHANGELOG.md does not contain a release heading for version '{version}'. "
            f"Expected a heading like '## {version}' or '## [{version}]'."
        )

    if tag:
        _validate_tag(tag.strip(), version)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that pyproject.toml version, changelog entries, and release tag metadata are consistent."
        )
    )
    parser.add_argument(
        "--git-tag",
        default=None,
        help="Git tag to validate (for example: v1.2.3). If omitted, tag validation is skipped.",
    )
    args = parser.parse_args()

    try:
        validate_release_metadata(args.git_tag)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    version = _read_project_version()
    tag_status = args.git_tag if args.git_tag else "(skipped)"
    print(
        "Release metadata validation passed: "
        f"version={version}, changelog=ok, git_tag={tag_status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
