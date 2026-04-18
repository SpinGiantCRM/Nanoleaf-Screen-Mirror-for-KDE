#!/usr/bin/env python3
"""Validate release metadata consistency across core project files."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ in CI
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
CHANGELOG_PATH = ROOT / "docs" / "CHANGELOG.md"
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?P<prerelease>-(?:rc|beta|alpha)\d+)?$")
VERSION_PATTERN = re.compile(r"^(?P<version>\d+\.\d+\.\d+)(?P<prerelease>-(?:rc|beta|alpha)\d+)?$")


class ValidationError(Exception):
    """Raised when release metadata validation fails."""


@dataclass(frozen=True)
class VersionParts:
    base: str
    prerelease: str | None


def _read_project_version() -> str:
    with PYPROJECT_PATH.open("rb") as handle:
        payload = tomllib.load(handle)

    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValidationError(f"{PYPROJECT_PATH} is missing [project].")

    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValidationError(f"{PYPROJECT_PATH} has invalid project.version value.")

    return version.strip()


def _parse_version(raw: str) -> VersionParts:
    match = VERSION_PATTERN.fullmatch(raw.strip())
    if not match:
        raise ValidationError(
            f"Version format mismatch: got '{raw}', expected X.Y.Z with optional -rcN/-betaN/-alphaN."
        )
    return VersionParts(base=match.group("version"), prerelease=match.group("prerelease"))


def _changelog_has_version(version: str) -> bool:
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^##\s+(?:\[{re.escape(version)}\]|{re.escape(version)})(?:\s|$)",
        flags=re.MULTILINE,
    )
    return pattern.search(text) is not None


def _validate_tag(git_tag: str, project_version: str) -> None:
    tag_match = TAG_PATTERN.fullmatch(git_tag.strip())
    if not tag_match:
        raise ValidationError(
            f"Git tag format mismatch: got '{git_tag}', expected 'vX.Y.Z' (optionally with -rcN/-betaN/-alphaN)."
        )

    parsed_project = _parse_version(project_version)
    tag_base = tag_match.group("version")

    if parsed_project.base != tag_base:
        raise ValidationError(
            "Git tag version mismatch: "
            f"pyproject.toml has '{project_version}' (normalized to '{parsed_project.base}'), "
            f"but git tag '{git_tag}' points to '{tag_base}'. "
            f"Expected tag 'v{parsed_project.base}' or prerelease variant like 'v{parsed_project.base}-rc1'."
        )


def validate_release_metadata(git_tag: str | None) -> str:
    project_version = _read_project_version()
    _parse_version(project_version)

    if not _changelog_has_version(project_version):
        raise ValidationError(
            f"docs/CHANGELOG.md is missing release heading for '{project_version}'."
        )

    if git_tag:
        _validate_tag(git_tag, project_version)

    return (
        "Release metadata validation passed: "
        f"version={project_version}, changelog=ok, git_tag={git_tag or '(skipped)'}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate pyproject version, changelog headings, and optional git-tag compatibility."
    )
    parser.add_argument("--git-tag", default=None)
    args = parser.parse_args()

    try:
        print(validate_release_metadata(args.git_tag))
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
