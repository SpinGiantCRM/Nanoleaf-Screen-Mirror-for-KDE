from __future__ import annotations

from typing import Optional, Sequence

from nanoleaf_sync.device.interfaces import NanoleafUSBIds


class HIDTransport:
    """HID transport wrapper around hidapi with report framing and reads."""

    def __init__(
        self,
        *,
        ids: NanoleafUSBIds,
        report_size: int = 64,
        read_timeout_ms: int = 500,
        use_report_id_prefix: bool = True,
    ) -> None:
        self.ids = ids
        self.report_size = int(report_size)
        self.read_timeout_ms = int(read_timeout_ms)
        self.use_report_id_prefix = bool(use_report_id_prefix)
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
        try:
            self._handle.open(self.ids.vid, self.ids.pid)
        except Exception as exc:
            self._handle = None
            raise RuntimeError(
                "Failed to open Nanoleaf HID device. Check Linux HID permissions "
                "(udev/group access) and that no other process has claimed the device."
            ) from exc

    def _build_report(self, payload: bytes) -> bytes:
        if self.use_report_id_prefix:
            report = bytearray(self.report_size + 1)
            report[0] = 0x00
            report[1 : 1 + len(payload)] = payload
            return bytes(report)

        report = bytearray(self.report_size)
        report[: len(payload)] = payload
        return bytes(report)

    def write(self, report: bytes | bytearray | memoryview | Sequence[int]) -> None:
        if self._handle is None:
            raise RuntimeError("HID transport not opened.")
        if isinstance(report, (bytes, bytearray, memoryview)):
            payload = bytes(report)
        else:
            payload = bytes(report)

        payload_capacity = self.report_size
        for offset in range(0, len(payload), payload_capacity):
            chunk = payload[offset : offset + payload_capacity]
            self._handle.write(self._build_report(chunk))

    def read(self) -> bytes:
        if self._handle is None:
            raise RuntimeError("HID transport not opened.")
        data = self._handle.read(self.report_size + (1 if self.use_report_id_prefix else 0), self.read_timeout_ms)
        if not data:
            return b""
        raw = bytes(data)
        if self.use_report_id_prefix and len(raw) >= 1:
            return raw[1:]
        return raw

    def transceive(self, request: bytes) -> bytes:
        """Write TLV request bytes and read enough framed HID bytes for a full TLV response."""
        self.write(request)

        response = bytearray()
        expected_len: int | None = None
        while True:
            chunk = self.read()
            if not chunk:
                raise RuntimeError(
                    f"Timed out waiting for HID response after receiving {len(response)} bytes"
                )
            response.extend(chunk)

            if expected_len is None and len(response) >= 3:
                payload_len = int.from_bytes(response[1:3], byteorder="big")
                expected_len = 3 + payload_len

            if expected_len is not None and len(response) >= expected_len:
                return bytes(response[:expected_len])

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None
