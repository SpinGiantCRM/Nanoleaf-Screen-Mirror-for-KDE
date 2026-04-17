from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_arch_packaging_assets_exist() -> None:
    assert (REPO_ROOT / "packaging" / "arch" / "PKGBUILD").exists()
    assert (REPO_ROOT / "packaging" / "arch" / "nanoleaf-kde-sync.install").exists()


def test_desktop_entry_references_installed_icon() -> None:
    desktop = (REPO_ROOT / "docs" / "nanoleaf-kde-sync.desktop").read_text(encoding="utf-8")
    assert "Exec=nanoleaf-kde-sync" in desktop
    assert "Icon=nanoleaf-kde-sync" in desktop


def test_packaged_icon_and_udev_rule_exist() -> None:
    assert (
        REPO_ROOT
        / "assets"
        / "icons"
        / "hicolor"
        / "scalable"
        / "apps"
        / "nanoleaf-kde-sync.svg"
    ).exists()
    assert (REPO_ROOT / "assets" / "udev" / "60-nanoleaf-kde-sync.rules").exists()
