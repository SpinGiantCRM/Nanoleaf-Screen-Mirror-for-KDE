from __future__ import annotations

import time
from typing import Any, Optional, Sequence

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

    @staticmethod
    def _fmt_path(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "<unknown>")

    @classmethod
    def _describe_candidate(cls, device: dict[str, Any]) -> str:
        path = cls._fmt_path(device.get("path"))
        interface = device.get("interface_number")
        usage_page = device.get("usage_page")
        usage = device.get("usage")
        serial = device.get("serial_number")
        return (
            f"path={path} interface={interface!r} usage_page={usage_page!r} "
            f"usage={usage!r} serial={serial!r}"
        )

    @staticmethod
    def _tlv_expected_len(buf: bytearray, expected_type: int) -> int | None:
        if len(buf) < 3:
            return None
        if buf[0] != expected_type:
            return None
        return 3 + int.from_bytes(buf[1:3], byteorder="big")

    def open(self) -> None:
        try:
            import hid  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "hidapi bindings not installed. Install `hidapi` package."
            ) from e

        devices = list(hid.enumerate(self.ids.vid, self.ids.pid))
        if not devices:
            raise RuntimeError(
                f"Nanoleaf device not found VID={self.ids.vid:#06x} PID={self.ids.pid:#06x}"
            )

        self._handle = hid.device()
        attempt_results: list[str] = []
        seen_paths: set[str] = set()
        candidates = [dev for dev in devices if isinstance(dev, dict)]

        def _candidate_sort_key(dev: dict[str, Any]) -> tuple[int, str]:
            interface = dev.get("interface_number")
            try:
                interface_key = 9999 if interface is None else int(interface)
            except Exception:
                interface_key = 9999
            return (interface_key, self._fmt_path(dev.get("path")))

        sorted_devices = sorted(candidates, key=_candidate_sort_key)
        for dev in sorted_devices:
            path = dev.get("path")
            path_text = self._fmt_path(path)
            if path_text in seen_paths:
                continue
            seen_paths.add(path_text)
            if not path:
                attempt_results.append(f"open_path({path_text}) skipped: missing path")
                continue
            try:
                self._handle.open_path(path)
                return
            except Exception as exc:
                attempt_results.append(
                    f"open_path({path_text}) failed: {type(exc).__name__}: {exc}"
                )

        try:
            self._handle.open(self.ids.vid, self.ids.pid)
            return
        except Exception as exc:
            attempt_results.append(
                f"open({self.ids.vid:#06x}, {self.ids.pid:#06x}) failed: {type(exc).__name__}: {exc}"
            )
            self._handle = None
            candidate_text = "; ".join(self._describe_candidate(dev) for dev in sorted_devices)
            if not candidate_text:
                candidate_text = "<none>"
            attempts = (
                "; ".join(attempt_results)
                if attempt_results
                else "no open attempts were made"
            )
            raise RuntimeError(
                "Failed to open Nanoleaf HID device after enumeration. "
                f"Enumerated candidates: {candidate_text}. Attempt results: {attempts}. "
                "This usually indicates one of: wrong interface/path selected by backend, busy device handle, "
                "hidapi backend mismatch, or insufficient permissions."
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
        """Write TLV request bytes and read enough framed HID bytes for a full TLV response.

        Root cause note: some devices (for example NL82K2 firmware variants) return 64-byte
        responses without a report-id prefix even when writes include one. If we always strip a
        leading byte from reads, we can drop the real TLV type byte and wait forever on malformed
        length accounting. We therefore evaluate both framing variants and accept the first
        complete TLV that matches the expected response type.
        """
        self.write(request)

        expected_type = (request[0] + 0x80) & 0xFF
        preferred_first = bool(self.use_report_id_prefix)
        # first candidate = preferred behavior for compatibility with existing devices.
        candidates = [
            {"strip_prefix": preferred_first, "buffer": bytearray(), "expected_len": None},
            {"strip_prefix": not preferred_first, "buffer": bytearray(), "expected_len": None},
        ]

        guard_window_s = max(1.0, float(self.read_timeout_ms) / 1000.0 * 4.0)
        deadline = time.monotonic() + guard_window_s
        while True:
            if time.monotonic() >= deadline:
                received = max(len(c["buffer"]) for c in candidates)
                raise RuntimeError(
                    "Malformed HID response: failed to assemble expected TLV "
                    f"within {guard_window_s:.2f}s after receiving {received} bytes"
                )
            # Read up to report-size + report-id byte. hidapi may still return 64 bytes.
            raw_chunk = self._handle.read(self.report_size + 1, self.read_timeout_ms)
            if not raw_chunk:
                received = max(len(c["buffer"]) for c in candidates)
                raise RuntimeError(
                    f"Timed out waiting for HID response after receiving {received} bytes"
                )
            raw = bytes(raw_chunk)
            for candidate in candidates:
                chunk = raw[1:] if candidate["strip_prefix"] and raw else raw
                if not chunk:
                    continue
                candidate["buffer"].extend(chunk)
                if candidate["expected_len"] is None:
                    candidate["expected_len"] = self._tlv_expected_len(
                        candidate["buffer"], expected_type
                    )
                expected_len = candidate["expected_len"]
                if expected_len is not None and len(candidate["buffer"]) >= expected_len:
                    return bytes(candidate["buffer"][:expected_len])

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None
