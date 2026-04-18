from __future__ import annotations

import re
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig


REPO_ROOT = Path(__file__).resolve().parents[1]


def _match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    assert match, f"Pattern not found: {pattern}"
    return match.group(1)


def test_version_metadata_is_consistent_between_pyproject_and_pkgbuild() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pkgbuild = (REPO_ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")

    pyproject_version = _match(r'^version = "([^"]+)"$', pyproject)
    pkgver = _match(r"^pkgver=([^\n]+)$", pkgbuild)

    assert pyproject_version == pkgver


def test_standalone_installer_uses_external_udev_rule_asset() -> None:
    installer = (REPO_ROOT / "install-nanoleaf-kde-sync.sh").read_text(encoding="utf-8")

    assert "assets/udev/$UDEV_RULE_NAME" in installer
    assert "cat > \"$temp_rule\" <<'RULES'" not in installer


def test_appimage_launcher_uses_matching_python_version() -> None:
    script = (REPO_ROOT / "scripts" / "build-appimage.sh").read_text(encoding="utf-8")

    assert 'PYTHON_STANDALONE_VERSION="3.11"' in script
    assert 'export PYTHONHOME="\\$PYTHON_ROOT"' in script
    assert (
        'export PYTHONPATH="\\$PYTHON_ROOT/lib/python${PYTHON_STANDALONE_VERSION}/site-packages'
        '\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script
    )
    assert 'exec "\\$PYTHON_ROOT/bin/python3" -m nanoleaf_sync.ui.tray "\\$@"' in script


def test_default_real_capture_backend_is_kwin_dbus() -> None:
    assert AppConfig.prefer_backend == "kwin-dbus"


def test_arch_docs_keep_makepkg_primary_and_appimage_secondary() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    install_arch = (REPO_ROOT / "docs" / "INSTALL_ARCH.md").read_text(encoding="utf-8")

    assert "Primary install path (recommended for Arch/CachyOS KDE users)" in readme
    assert "makepkg -si" in readme
    assert "AppImage installer (experimental on Arch/CachyOS)" in readme
    assert "Primary user path (recommended)" in install_arch
    assert "Secondary path: standalone AppImage installer (experimental on Arch/CachyOS)" in install_arch
