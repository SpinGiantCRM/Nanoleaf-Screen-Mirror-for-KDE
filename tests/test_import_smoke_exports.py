from __future__ import annotations

import numpy as np


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


def test_average_color_runtime_public_path_smoke() -> None:
    from nanoleaf_sync.runtime.zones import average_color

    image = np.array([[[1, 2, 3], [5, 6, 7]]], dtype=np.uint8)

    assert average_color(image) == (3, 4, 5)
