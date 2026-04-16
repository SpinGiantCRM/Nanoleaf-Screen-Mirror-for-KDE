from __future__ import annotations

from nanoleaf_sync.device.interfaces import DeviceDriver
from nanoleaf_sync.device.mock_driver import MockNanoleafUSBDriver


def test_mock_driver_implements_contract() -> None:
    driver = MockNanoleafUSBDriver()
    assert isinstance(driver, DeviceDriver)

    driver.initialize()
    driver.send_frame([(1, 2, 3), (4, 5, 6)])
    assert driver.last_colors == [(1, 2, 3), (4, 5, 6)]
    driver.close()
