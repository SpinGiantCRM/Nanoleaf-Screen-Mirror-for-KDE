from __future__ import annotations


def test_device_package_exports_import() -> None:
    from nanoleaf_sync.device import (
        DeviceDriver,
        DriverCapabilities,
        NanoleafUSBDriver,
        NanoleafUSBIds,
    )

    assert DeviceDriver is not None
    assert DriverCapabilities is not None
    assert NanoleafUSBIds is not None
    assert NanoleafUSBDriver is not None
