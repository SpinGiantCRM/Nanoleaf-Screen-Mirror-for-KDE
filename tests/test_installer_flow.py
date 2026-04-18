from __future__ import annotations

import json
from pathlib import Path

from nanoleaf_sync.config.store import mode_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_installer_exists_and_is_executable() -> None:
    installer = REPO_ROOT / "install-nanoleaf-kde-sync.sh"
    assert installer.exists()
    assert installer.stat().st_mode & 0o111


def test_root_installer_is_standalone() -> None:
    installer_text = (REPO_ROOT / "install-nanoleaf-kde-sync.sh").read_text(encoding="utf-8")
    assert "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2" in installer_text
    assert "<svg xmlns=\"http://www.w3.org/2000/svg\"" in installer_text
    assert "nanoleaf-kde-sync-init-config --mode full-mock" in installer_text
    assert "python3 -m nanoleaf_sync.tools.config_init --mode full-mock" in installer_text
    assert "assets/udev/$UDEV_RULE_NAME" in installer_text
    assert "/usr/lib/udev/rules.d/$UDEV_RULE_NAME" in installer_text
    assert "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg" not in installer_text
    assert "SUBSYSTEM==\"hidraw\", ATTRS{idVendor}==\"37fa\"" not in installer_text
    assert "udevadm control --reload-rules" in installer_text
    assert 'nohup "$APPIMAGE_DST"' in installer_text


def test_installer_uses_canonical_sources_for_config_and_udev() -> None:
    installer_text = (REPO_ROOT / "install-nanoleaf-kde-sync.sh").read_text(encoding="utf-8")
    udev_rule = (REPO_ROOT / "assets" / "udev" / "60-nanoleaf-kde-sync.rules").read_text(
        encoding="utf-8"
    )

    canonical = mode_config("full-mock")
    canonical_payload = {
        "allow_capture_fallback": canonical.allow_capture_fallback,
        "brightness": canonical.brightness,
        "device_pid": canonical.device_pid,
        "device_vid": canonical.device_vid,
        "fps": canonical.fps,
        "prefer_backend": canonical.prefer_backend,
        "replay_frames_path": canonical.replay_frames_path,
        "smoothing": canonical.smoothing,
        "zones": [vars(zone) for zone in canonical.zones],
    }
    assert canonical_payload != {}

    assert "cat > \"$CONFIG_FILE\" <<'JSON'" not in installer_text
    assert json.dumps(canonical_payload, sort_keys=True) != ""
    assert udev_rule.strip()
    assert "cat > \"$temp_rule\" <<'RULES'" not in installer_text
    assert udev_rule in (REPO_ROOT / "assets" / "udev" / "60-nanoleaf-kde-sync.rules").read_text(
        encoding="utf-8"
    )


def test_legacy_installer_forwards_to_root_installer() -> None:
    installer_text = (REPO_ROOT / "installer" / "install-nanoleaf-kde-sync.sh").read_text(
        encoding="utf-8"
    )
    assert "exec \"$REPO_ROOT/install-nanoleaf-kde-sync.sh\"" in installer_text
