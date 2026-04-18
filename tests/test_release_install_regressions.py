from __future__ import annotations

import re
from pathlib import Path


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


def test_standalone_installer_temp_rule_cleanup_is_set_u_safe() -> None:
    installer = (REPO_ROOT / "install-nanoleaf-kde-sync.sh").read_text(encoding="utf-8")

    # Regression check for the "temp_rule: unbound variable" cleanup crash.
    assert "trap 'rm -f -- \"'\"$temp_rule\"'\"' RETURN" in installer


def test_appimage_launcher_uses_matching_python_version() -> None:
    script = (REPO_ROOT / "scripts" / "build-appimage.sh").read_text(encoding="utf-8")

    assert 'PYTHON_VERSION="3.11"' in script
    assert 'PYTHON_BIN="python${PYTHON_VERSION}"' in script
    assert 'exec python3.11 -m nanoleaf_sync.ui.tray "$@"' in script
