from __future__ import annotations

from nanoleaf_sync.tools.output_format import describe_mode


def test_describe_mode_labels() -> None:
    capture, device = describe_mode(
        True,
        "kwin-dbus",
        service_running=False,
        device_discovered=False,
    )
    assert capture == "Mock capture"
    assert device == "USB device: not started"

    capture, device = describe_mode(
        False,
        "kwin-dbus",
        service_running=True,
        device_discovered=True,
        device_model="NL82K2",
    )
    assert capture == "Capture: kwin-dbus"
    assert device == "USB device: connected (NL82K2)"
