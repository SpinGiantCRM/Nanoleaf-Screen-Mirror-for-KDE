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


def test_ci_workflows_exist() -> None:
    assert (REPO_ROOT / ".github" / "workflows" / "ci.yml").exists()
    assert (REPO_ROOT / ".github" / "workflows" / "build.yml").exists()
    assert (REPO_ROOT / ".github" / "workflows" / "release.yml").exists()


def test_primary_installer_assets_exist() -> None:
    assert (REPO_ROOT / "install-nanoleaf-kde-sync.sh").exists()
    assert (REPO_ROOT / "installer" / "install-nanoleaf-kde-sync.sh").exists()


def test_pkbuild_installs_rc_support_docs() -> None:
    pkgbuild = (REPO_ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    assert 'docs/INSTALL_ARCH.md "$pkgdir/usr/share/doc/$pkgname/INSTALL_ARCH.md"' in pkgbuild
    assert 'docs/TROUBLESHOOTING.md "$pkgdir/usr/share/doc/$pkgname/TROUBLESHOOTING.md"' in pkgbuild


def test_install_and_hardware_docs_reference_consistent_udev_paths() -> None:
    install_doc = (REPO_ROOT / "docs" / "INSTALL_ARCH.md").read_text(encoding="utf-8")
    hardware_doc = (REPO_ROOT / "docs" / "HARDWARE_SETUP.md").read_text(encoding="utf-8")

    assert "makepkg -si" in install_doc
    assert "recommended end-user path on Arch/CachyOS KDE" in install_doc
    assert "/usr/lib/udev/rules.d/" in hardware_doc
    assert "assets/udev/60-nanoleaf-kde-sync.rules" in hardware_doc
