from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_installer_exists_and_is_executable() -> None:
    installer = REPO_ROOT / "install-nanoleaf-kde-sync.sh"
    assert installer.exists()
    assert installer.stat().st_mode & 0o111


def test_root_installer_is_standalone() -> None:
    installer_text = (REPO_ROOT / "install-nanoleaf-kde-sync.sh").read_text(encoding="utf-8")
    assert "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2" in installer_text
    assert "<svg xmlns=\"http://www.w3.org/2000/svg\"" in installer_text
    assert "SUBSYSTEM==\"hidraw\", ATTRS{idVendor}==\"37fa\"" in installer_text
    assert "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg" not in installer_text
    assert "assets/udev/60-nanoleaf-kde-sync.rules" not in installer_text
    assert "udevadm control --reload-rules" in installer_text
    assert 'nohup "$APPIMAGE_DST"' in installer_text


def test_legacy_installer_forwards_to_root_installer() -> None:
    installer_text = (REPO_ROOT / "installer" / "install-nanoleaf-kde-sync.sh").read_text(
        encoding="utf-8"
    )
    assert "exec \"$REPO_ROOT/install-nanoleaf-kde-sync.sh\"" in installer_text
