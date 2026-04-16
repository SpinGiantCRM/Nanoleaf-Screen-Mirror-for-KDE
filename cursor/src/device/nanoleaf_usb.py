from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


RGBTuple = Tuple[int, int, int]


@dataclass(frozen=True)
class NanoleafUSBIds:
    # Placeholder values until you have the official protocol/spec.
    vid: int
    pid: int


class NanoleafPCScreenMirrorProtocolStub:
    """
    Placeholder protocol packer for "PC Screen Mirror LS over USB".

    This module intentionally DOES NOT implement the official byte layout yet.
    It exists so that once you receive the official HID report specification,
    you only need to update `build_hid_report()` without touching:
    - USB device discovery/transport
    - capture/color/calibration pipeline
    - service timing/scheduling
    """

    def __init__(self, *, report_size: int = 64) -> None:
        self.report_size = int(report_size)

    def build_hid_report(self, colors: Sequence[RGBTuple]) -> List[int]:
        # Build a fixed-size placeholder report.
        report = [0x00] * self.report_size

        # Tiny header marker so you can verify the packing path during debugging.
        # This is NOT an official Nanoleaf command byte.
        header_offset = 1
        if self.report_size >= 4:
            report[header_offset : header_offset + 3] = [0xAA, 0x55, 0x00]

        offset = header_offset + 3
        for (r, g, b) in colors:
            if offset + 3 > self.report_size:
                break
            report[offset] = int(max(0, min(255, r)))
            report[offset + 1] = int(max(0, min(255, g)))
            report[offset + 2] = int(max(0, min(255, b)))
            offset += 3

        return report


class HIDTransport:
    """
    HID transport wrapper around hidapi.

    Keeps USB discovery/IO separate from protocol packing logic.
    """

    def __init__(self, *, ids: NanoleafUSBIds) -> None:
        self.ids = ids
        self._handle: Optional[object] = None

    def open(self) -> None:
        try:
            import hid  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("hidapi bindings not installed. Install `hidapi` package.") from e

        # Ensure device exists first (clear error message).
        found = False
        for _dev in hid.enumerate(self.ids.vid, self.ids.pid):
            found = True
            break
        if not found:
            raise RuntimeError(f"Nanoleaf device not found VID={self.ids.vid:#06x} PID={self.ids.pid:#06x}")

        self._handle = hid.device()
        self._handle.open(self.ids.vid, self.ids.pid)

    def write(self, report: Sequence[int]) -> None:
        if self._handle is None:
            raise RuntimeError("HID transport not opened.")
        self._handle.write(list(report))

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None


class NanoleafUSBDriver:
    """
    Nanoleaf USB HID driver (protocol stub).

    This class is designed so that once you receive the "PC Screen Mirror
    Light Strip protocol over USB specification", you only need to update:
    - `send_frame(colors)` report packing
    - `initialize_device()` (if required by the protocol)

    Current behavior:
    - If `hidapi` bindings are not available, the driver raises at initialize-time.
    - `send_frame` uses a placeholder protocol packer until the official spec
      is provided, but still exercises the full USB write path.
    """

    def __init__(self, *, ids: NanoleafUSBIds, report_size: int = 64) -> None:
        self.ids = ids
        self.report_size = report_size
        self._transport = HIDTransport(ids=ids)
        self._protocol = NanoleafPCScreenMirrorProtocolStub(report_size=report_size)

    def initialize(self) -> None:
        """
        Initialize the HID connection and send any protocol init sequence (stub).
        """
        self._transport.open()

        # Protocol initialization placeholder:
        # - Some devices require a handshake, mode switch, or enabling "screen mirror" stream.
        # - When spec arrives, implement the byte sequence here.
        #
        # For now, we do nothing beyond opening the handle.

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        """
        Send a single frame worth of colors to the Nanoleaf device (stub).

        Args:
            colors: list of (r, g, b) tuples for each LED zone/pixel group.

        Protocol placeholder:
            The official HID report format will typically include:
            - report id / header bytes
            - zone count / frame counter (if required)
            - packed RGB triplets (often as per-zone or per-pixel)
            - a checksum or footer (depending on device model)

        Current implementation:
            - Packs a simple payload into a fixed-size report.
            - Does not implement real Nanoleaf protocol bytes until the spec is provided.
        """

        report = self._protocol.build_hid_report(colors)
        self._transport.write(report)

    def close(self) -> None:
        self._transport.close()


class MockNanoleafUSBDriver(NanoleafUSBDriver):
    """
    Mock driver for development/testing without real Nanoleaf hardware.
    """

    def __init__(self, *, report_size: int = 64, ids: Optional[NanoleafUSBIds] = None) -> None:
        if ids is None:
            ids = NanoleafUSBIds(vid=0x0, pid=0x0)
        super().__init__(ids=ids, report_size=report_size)
        self.last_colors: Optional[Sequence[RGBTuple]] = None
        self._initialized = False

    def initialize(self) -> None:
        self._initialized = True

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        if not self._initialized:
            raise RuntimeError("Mock driver not initialized. Call initialize() first.")
        self.last_colors = list(colors)
        # Print a small sample to avoid flooding stdout at 30 FPS.
        sample = self.last_colors[: min(3, len(self.last_colors))]
        print(f"[mock-usb] frame zones={len(self.last_colors)} sample={sample}")

    def close(self) -> None:
        self._initialized = False
        # No real transport was opened, but keep semantics consistent.
        try:
            self._transport.close()
        except Exception:
            pass

