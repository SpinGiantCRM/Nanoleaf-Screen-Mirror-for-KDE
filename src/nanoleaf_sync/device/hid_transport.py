from __future__ import annotations

from typing import Optional, Sequence

from nanoleaf_sync.device.interfaces import NanoleafUSBIds


class HIDTransport:
    """HID transport wrapper around hidapi."""

    def __init__(self, *, ids: NanoleafUSBIds) -> None:
        self.ids = ids
        self._handle: Optional[object] = None

    def open(self) -> None:
        try:
            import hid  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "hidapi bindings not installed. Install `hidapi` package."
            ) from e

        found = False
        for _dev in hid.enumerate(self.ids.vid, self.ids.pid):
            found = True
            break
        if not found:
            raise RuntimeError(
                f"Nanoleaf device not found VID={self.ids.vid:#06x} PID={self.ids.pid:#06x}"
            )

        self._handle = hid.device()
        self._handle.open(self.ids.vid, self.ids.pid)

    def write(self, report: bytes | bytearray | memoryview | Sequence[int]) -> None:
        if self._handle is None:
            raise RuntimeError("HID transport not opened.")
        if isinstance(report, (bytes, bytearray, memoryview)):
            self._handle.write(report)
            return
        self._handle.write(bytes(report))

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None
