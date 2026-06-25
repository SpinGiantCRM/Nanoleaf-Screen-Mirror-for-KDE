#!/usr/bin/env python3
"""Validate built wheel platform tags and required package contents."""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PACKAGE_ASSETS: tuple[str, ...] = (
    "VERSION",
    "ui/style.qss",
    "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg",
    "assets/udev/60-nanoleaf-kde-sync.rules",
    "capture/nanoleaf_drm_helper",
)

WHEEL_TAG_RE = re.compile(r"^Tag: (.+)$", re.MULTILINE)
ELF_MAGIC = b"\x7fELF"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def expected_console_scripts() -> tuple[str, ...]:
    pyproject = ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict) or not scripts:
        fail("pyproject.toml is missing [project.scripts] console entry points")
    return tuple(sorted(str(name) for name in scripts))


def wheel_member_paths(archive: zipfile.ZipFile) -> set[str]:
    return set(archive.namelist())


def package_asset_paths(archive: zipfile.ZipFile) -> set[str]:
    marker = "/nanoleaf_sync/"
    paths: set[str] = set()
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        idx = name.find(marker)
        if idx == -1:
            continue
        relative = name[idx + len(marker) :]
        if relative:
            paths.add(relative)
    return paths


def read_wheel_tags(archive: zipfile.ZipFile) -> list[str]:
    wheel_info_paths = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
    if len(wheel_info_paths) != 1:
        fail(f"expected exactly one WHEEL metadata file, found {len(wheel_info_paths)}")
    wheel_text = archive.read(wheel_info_paths[0]).decode("utf-8")
    tags = WHEEL_TAG_RE.findall(wheel_text)
    if not tags:
        fail("WHEEL metadata is missing Tag entries")
    return tags


def read_console_scripts(archive: zipfile.ZipFile) -> set[str]:
    entry_point_paths = [
        name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
    ]
    if len(entry_point_paths) != 1:
        fail(f"expected exactly one entry_points.txt file, found {len(entry_point_paths)}")
    parser = configparser.ConfigParser()
    parser.read_string(archive.read(entry_point_paths[0]).decode("utf-8"))
    if "console_scripts" not in parser:
        fail("entry_points.txt is missing [console_scripts]")
    return set(parser["console_scripts"])


def validate_wheel(path: Path) -> None:
    if not path.is_file():
        fail(f"wheel not found: {path}")
    if path.suffix != ".whl":
        fail(f"not a wheel file: {path}")

    if not path.name.endswith("-linux_x86_64.whl"):
        fail(f"wheel filename must end with -linux_x86_64.whl, got: {path.name}")

    with zipfile.ZipFile(path) as archive:
        tags = read_wheel_tags(archive)
        if any("any" in tag for tag in tags):
            fail(f"wheel must not be tagged py3-none-any; tags={tags!r}")
        if not any("linux_x86_64" in tag for tag in tags):
            fail(f"wheel is missing linux_x86_64 tag; tags={tags!r}")

        assets = package_asset_paths(archive)
        missing_assets = [
            relative_path
            for relative_path in REQUIRED_PACKAGE_ASSETS
            if relative_path not in assets
        ]
        if missing_assets:
            fail(f"wheel is missing required package assets: {', '.join(missing_assets)}")

        helper_paths = [
            name
            for name in archive.namelist()
            if name.endswith("nanoleaf_sync/capture/nanoleaf_drm_helper")
        ]
        if len(helper_paths) != 1:
            fail("wheel must contain exactly one nanoleaf_drm_helper binary")
        helper_bytes = archive.read(helper_paths[0])
        if not helper_bytes:
            fail("nanoleaf_drm_helper is empty")
        if not helper_bytes.startswith(ELF_MAGIC):
            fail("nanoleaf_drm_helper is not an ELF binary")

        console_scripts = read_console_scripts(archive)
        expected_scripts = set(expected_console_scripts())
        missing_scripts = sorted(expected_scripts - console_scripts)
        if missing_scripts:
            fail(f"wheel is missing console scripts: {', '.join(missing_scripts)}")

        members = wheel_member_paths(archive)
        if not any("/nanoleaf_sync/" in member for member in members):
            fail("wheel does not contain nanoleaf_sync package files")

    print(f"OK: validated wheel {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "wheels",
        nargs="+",
        type=Path,
        help="wheel file(s) to validate",
    )
    args = parser.parse_args(argv)
    for wheel_path in args.wheels:
        validate_wheel(wheel_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
