from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_simple_installer_exists_and_is_executable() -> None:
    installer = REPO_ROOT / "installer" / "install-nanoleaf-kde-sync.sh"
    assert installer.exists()
    assert installer.stat().st_mode & 0o111


def test_installer_handles_desktop_icon_udev_and_launch() -> None:
    installer_text = (REPO_ROOT / "installer" / "install-nanoleaf-kde-sync.sh").read_text(
        encoding="utf-8"
    )
    assert "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2" in installer_text
    assert "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg" in installer_text
    assert "assets/udev/60-nanoleaf-kde-sync.rules" in installer_text
    assert "udevadm control --reload-rules" in installer_text
    assert 'nohup "$APPIMAGE_DST"' in installer_text
