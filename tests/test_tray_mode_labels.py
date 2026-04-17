from __future__ import annotations

from nanoleaf_sync.ui.tray_app import describe_mode


def test_describe_mode_labels() -> None:
    capture, device = describe_mode(True, True, "kwin-dbus")
    assert capture == "Mock capture"
    assert device == "Mock device"

    capture, device = describe_mode(False, False, "kwin-dbus")
    assert capture == "Capture: kwin-dbus"
    assert device == "Real USB device"
