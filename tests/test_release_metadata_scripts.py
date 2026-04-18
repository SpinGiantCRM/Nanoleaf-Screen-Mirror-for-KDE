from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative_path: str, module_name: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_release_version = _load_module("scripts/sync_release_version.py", "sync_release_version")
validate_release_metadata = _load_module("scripts/validate_release_metadata.py", "validate_release_metadata")


@pytest.mark.parametrize(
    ("tag", "expected_version"),
    [
        ("v0.3.0", "0.3.0"),
        ("v0.3.0-rc2", "0.3.0"),
        ("v2.1.4-beta3", "2.1.4"),
        ("v10.9.8-alpha1", "10.9.8"),
    ],
)
def test_version_from_tag_accepts_stable_and_prerelease(tag: str, expected_version: str) -> None:
    assert sync_release_version._version_from_tag(tag) == expected_version


@pytest.mark.parametrize("tag", ["0.3.0", "v0.3", "v0.3.0-rc", "v0.3.0-gamma1"])
def test_version_from_tag_rejects_unsupported_formats(tag: str) -> None:
    with pytest.raises(ValueError, match=r"Expected 'vX.Y.Z' \(optionally with -rcN/-betaN/-alphaN\)"):
        sync_release_version._version_from_tag(tag)


@pytest.mark.parametrize("tag", ["v0.3.0", "v0.3.0-rc2", "v0.3.0-beta1", "v0.3.0-alpha1"])
def test_validate_tag_accepts_stable_and_prerelease_tags(tag: str) -> None:
    validate_release_metadata._validate_tag(tag, "0.3.0")


def test_validate_tag_accepts_when_project_version_is_prerelease() -> None:
    validate_release_metadata._validate_tag("v0.3.0-rc2", "0.3.0-rc2")


@pytest.mark.parametrize(
    ("tag", "version", "error_match"),
    [
        (
            "release-0.3.0",
            "0.3.0",
            r"expected 'vX.Y.Z' \(optionally with -rcN/-betaN/-alphaN\)",
        ),
        (
            "v0.3.1",
            "0.3.0",
            "normalized to '0.3.0'",
        ),
        (
            "v0.3.1-rc1",
            "0.3.0-rc1",
            "Expected tag 'v0.3.0' or prerelease variant like 'v0.3.0-rc1'",
        ),
    ],
)
def test_validate_tag_rejects_mismatched_or_invalid_tags(tag: str, version: str, error_match: str) -> None:
    with pytest.raises(validate_release_metadata.ValidationError, match=error_match):
        validate_release_metadata._validate_tag(tag, version)
