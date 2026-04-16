from __future__ import annotations

from device.interfaces import DeviceDriver
from device.nanoleaf_usb import MockNanoleafUSBDriver, NanoleafUSBIds


def test_mock_driver_implements_contract() -> None:
    driver = MockNanoleafUSBDriver(ids=NanoleafUSBIds(vid=0x0, pid=0x0))
    assert isinstance(driver, DeviceDriver)

    driver.initialize()
    driver.send_frame([(1, 2, 3), (4, 5, 6)])
    assert driver.last_colors == [(1, 2, 3), (4, 5, 6)]
    driver.close()
