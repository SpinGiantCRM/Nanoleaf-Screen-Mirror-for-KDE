#!/usr/bin/env python3
"""Validate release version alignment across repo metadata and artifacts."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_version_file() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        fail(f"VERSION must be SemVer X.Y.Z, got: {version!r}")
    return version


def normalize_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    tag = tag.removeprefix("refs/tags/")
    if not tag.startswith("v"):
        fail(f"Release tag must start with 'v', got: {tag!r}")
    normalized = tag[1:]
    if not VERSION_RE.fullmatch(normalized):
        fail(f"Release tag must be in format vX.Y.Z, got: {tag!r}")
    return normalized


def parse_pkgbuild_pkgver() -> str:
    cmd = ["bash", "-lc", "set -euo pipefail; source PKGBUILD; printf '%s' \"$pkgver\""]
    completed = subprocess.run(
        cmd,
        cwd=ROOT / "packaging/arch",
        check=True,
        capture_output=True,
        text=True,
    )
    pkgver = completed.stdout.strip()
    if not pkgver:
        fail("Unable to evaluate pkgver from packaging/arch/PKGBUILD")
    return pkgver


def parse_readme_badge_version() -> str:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"badge/version-(\d+\.\d+\.\d+)-", readme_text)
    if not match:
        fail("Unable to find semantic version in README version badge.")
    return match.group(1)


def check_artifacts(version: str, *artifact_dirs: Path) -> None:
    expected_prefixes = (
        f"nanoleaf_kde_sync-{version}",
        f"Nanoleaf-Screen-Mirror-for-KDE-{version}",
    )
    saw_expected = False
    for artifact_dir in artifact_dirs:
        if not artifact_dir.exists():
            fail(f"Artifact directory does not exist: {artifact_dir}")
        for path in artifact_dir.iterdir():
            if path.suffix == ".sha256":
                continue
            name = path.name
            if any(name.startswith(prefix) for prefix in expected_prefixes):
                saw_expected = True
                continue
            fail(
                "Release artifact filename drift detected. "
                f"{name!r} does not start with one of {expected_prefixes!r}."
            )
    if not saw_expected:
        fail(
            "No release artifacts found with canonical version prefix "
            f"{expected_prefixes!r}."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag, e.g. v0.4.2", default="")
    parser.add_argument(
        "--artifact-dir",
        action="append",
        default=[],
        help="Directory containing built release assets to validate",
    )
    args = parser.parse_args()

    version = read_version_file()

    normalized_tag = normalize_tag(args.tag)
    if normalized_tag and normalized_tag != version:
        fail(
            f"Release tag version ({normalized_tag}) does not match VERSION ({version})."
        )

    pkgver = parse_pkgbuild_pkgver()
    if pkgver != version:
        fail(f"PKGBUILD pkgver ({pkgver}) does not match VERSION ({version}).")

    readme_version = parse_readme_badge_version()
    if readme_version != version:
        fail(
            f"README version badge ({readme_version}) does not match VERSION ({version})."
        )

    for artifact_dir in args.artifact_dir:
        check_artifacts(version, Path(artifact_dir))

    print(f"Version alignment OK: {version}")


if __name__ == "__main__":
    main()
