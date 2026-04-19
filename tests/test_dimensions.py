from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.capture import dimensions


def test_parse_mode_line() -> None:
    assert dimensions._parse_mode_line("3840x2160") == (3840, 2160)
    assert dimensions._parse_mode_line("1920x1080@60") == (1920, 1080)
    assert dimensions._parse_mode_line("invalid") is None


def test_detect_sysfs_prefers_largest_connected(monkeypatch, tmp_path: Path) -> None:
    drm = tmp_path / "drm"
    c1 = drm / "card0-HDMI-A-1"
    c2 = drm / "card0-DP-1"
    c1.mkdir(parents=True)
    c2.mkdir(parents=True)
    (c1 / "status").write_text("connected\n", encoding="utf-8")
    (c1 / "modes").write_text("1920x1080\n", encoding="utf-8")
    (c2 / "status").write_text("connected\n", encoding="utf-8")
    (c2 / "modes").write_text("3440x1440\n", encoding="utf-8")

    monkeypatch.setattr(dimensions, "Path", lambda p: drm if p == "/sys/class/drm" else Path(p))
    assert dimensions._detect_primary_screen_dims_sysfs() == (3440, 1440)
