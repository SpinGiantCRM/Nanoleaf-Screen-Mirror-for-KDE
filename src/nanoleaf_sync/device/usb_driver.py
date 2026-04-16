from __future__ import annotations

from typing import Sequence

from nanoleaf_sync.device.hid_transport import HIDTransport
from nanoleaf_sync.device.interfaces import DeviceDriver, DriverCapabilities, NanoleafUSBIds, RGBTuple
from nanoleaf_sync.device.protocol_stub import NanoleafPCScreenMirrorProtocolStub


class NanoleafUSBDriver(DeviceDriver):
    """Nanoleaf USB HID driver with protocol-stub report packing."""

    capabilities = DriverCapabilities(name="nanoleaf-usb-stub")

    def __init__(self, *, ids: NanoleafUSBIds, report_size: int = 64) -> None:
        self.ids = ids
        self.report_size = report_size
        self._transport = HIDTransport(ids=ids)
        self._protocol = NanoleafPCScreenMirrorProtocolStub(report_size=report_size)

    def initialize(self) -> None:
        self._transport.open()

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        report = self._protocol.build_hid_report(colors)
        self._transport.write(report)

    def close(self) -> None:
        self._transport.close()
