from __future__ import annotations

import importlib.util
import subprocess
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


def test_check_srcinfo_in_sync_accepts_matching_makepkg_output(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    arch_dir = tmp_path / "packaging" / "arch"
    arch_dir.mkdir(parents=True)
    expected = (
        "pkgbase = nanoleaf-kde-sync\n"
        "\tpkgver = 1.4.0\n"
        "\tsource = nanoleaf-kde-sync-1.4.0.tar.gz::"
        "https://example.invalid/v1.4.0.tar.gz\n"
        "\tsha256sums = abc123\n\n"
        "pkgname = nanoleaf-kde-sync\n"
    )
    (arch_dir / ".SRCINFO").write_text(expected, encoding="utf-8")
    module.ROOT = tmp_path
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/makepkg")

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["makepkg"], returncode=0, stdout=expected)

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.check_srcinfo_in_sync("1.4.0")


def test_check_srcinfo_in_sync_accepts_static_metadata_without_makepkg(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    arch_dir = tmp_path / "packaging" / "arch"
    arch_dir.mkdir(parents=True)
    (arch_dir / ".SRCINFO").write_text(
        "pkgbase = nanoleaf-kde-sync\n"
        "\tpkgver = 1.4.0\n"
        "\tsource = nanoleaf-kde-sync-1.4.0.tar.gz::"
        "https://example.invalid/v1.4.0.tar.gz\n"
        "\tsha256sums = abc123\n",
        encoding="utf-8",
    )
    module.ROOT = tmp_path
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("makepkg should be optional outside Arch"),
    )

    module.check_srcinfo_in_sync("1.4.0")


def test_check_srcinfo_in_sync_rejects_stale_metadata(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    arch_dir = tmp_path / "packaging" / "arch"
    arch_dir.mkdir(parents=True)
    (arch_dir / ".SRCINFO").write_text(
        "pkgbase = nanoleaf-kde-sync\n\tpkgver = 1.1.0\n",
        encoding="utf-8",
    )
    module.ROOT = tmp_path
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/makepkg")

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["makepkg"],
            returncode=0,
            stdout="pkgbase = nanoleaf-kde-sync\n\tpkgver = 1.4.0\n",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    with pytest.raises(SystemExit):
        module.check_srcinfo_in_sync("1.4.0")


def test_check_srcinfo_in_sync_rejects_skip_checksum_without_makepkg(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    arch_dir = tmp_path / "packaging" / "arch"
    arch_dir.mkdir(parents=True)
    (arch_dir / ".SRCINFO").write_text(
        "pkgbase = nanoleaf-kde-sync\n"
        "\tpkgver = 1.4.0\n"
        "\tsource = nanoleaf-kde-sync-1.4.0.tar.gz::"
        "https://example.invalid/v1.4.0.tar.gz\n"
        "\tsha256sums = SKIP\n",
        encoding="utf-8",
    )
    module.ROOT = tmp_path
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit):
        module.check_srcinfo_in_sync("1.4.0")
