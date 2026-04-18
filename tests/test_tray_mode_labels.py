from __future__ import annotations

from nanoleaf_sync.tools.output_format import describe_mode


def test_describe_mode_labels() -> None:
    capture, device = describe_mode(True, "kwin-dbus")
    assert capture == "Mock capture"
    assert device == "Real USB device"

    capture, device = describe_mode(False, "kwin-dbus")
    assert capture == "Capture: kwin-dbus"
    assert device == "Real USB device"
