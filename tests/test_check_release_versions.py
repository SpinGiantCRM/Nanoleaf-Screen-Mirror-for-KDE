from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_release_versions.py"
    spec = importlib.util.spec_from_file_location("check_release_versions", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_readme_badge_version_allows_no_badge(tmp_path: Path) -> None:
    module = _load_module()
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nNo badges here.\n", encoding="utf-8")
    module.ROOT = tmp_path

    assert module.parse_readme_badge_version() is None


def test_parse_readme_badge_version_reads_static_semver_badge(tmp_path: Path) -> None:
    module = _load_module()
    readme = tmp_path / "README.md"
    readme.write_text(
        "![Version](https://img.shields.io/badge/version-1.2.3-blue)\n",
        encoding="utf-8",
    )
    module.ROOT = tmp_path

    assert module.parse_readme_badge_version() == "1.2.3"


def test_parse_readme_badge_version_rejects_malformed_static_badge(tmp_path: Path) -> None:
    module = _load_module()
    readme = tmp_path / "README.md"
    readme.write_text(
        "![Version](https://img.shields.io/badge/version-latest-blue)\n",
        encoding="utf-8",
    )
    module.ROOT = tmp_path

    with pytest.raises(SystemExit):
        module.parse_readme_badge_version()
