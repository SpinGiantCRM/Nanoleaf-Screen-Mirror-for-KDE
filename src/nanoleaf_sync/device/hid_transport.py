from __future__ import annotations

import re
import time
from pathlib import Path
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
    def _looks_like_usb_interface_path(path_text: str) -> bool:
        return bool(re.fullmatch(r"\d+-[\d.]+:\d+\.\d+", path_text.strip()))

    @staticmethod
    def _candidate_open_paths(path_value: Any) -> list[bytes]:
        if not path_value:
            return []
        raw: bytes
        if isinstance(path_value, bytes):
            raw = path_value
        else:
            raw = str(path_value).encode("utf-8", errors="replace")

        path_text = raw.decode("utf-8", errors="replace").strip()
        candidates: list[bytes] = [raw]

        if HIDTransport._looks_like_usb_interface_path(path_text):
            # Linux: some hid backends enumerate USB interface IDs (for example "3-1:1.0")
            # while actual open requires a hidraw node path.
            sys_hidraw_dir = Path("/sys/bus/usb/devices") / path_text / "hidraw"
            try:
                for child in sorted(sys_hidraw_dir.iterdir()):
                    if child.name.startswith("hidraw"):
                        candidates.append(f"/dev/{child.name}".encode("utf-8"))
            except Exception:
                pass

        deduped: list[bytes] = []
        seen: set[bytes] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _hid_backend_metadata(hid_module: Any) -> str:
        module_file = str(getattr(hid_module, "__file__", "<unknown>") or "<unknown>")
        version = str(getattr(hid_module, "__version__", "<unknown>") or "<unknown>")
        backend = str(getattr(hid_module, "__hidapi_version__", "") or "").strip()
        extra = f", hidapi={backend}" if backend else ""
        return f"module={module_file}, version={version}{extra}"

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

        def _candidate_sort_key(dev: dict[str, Any]) -> tuple[int, int, str]:
            interface = dev.get("interface_number")
            try:
                interface_key = 9999 if interface is None else int(interface)
            except Exception:
                interface_key = 9999
            path_text = self._fmt_path(dev.get("path"))
            if path_text.startswith("/dev/hidraw"):
                path_kind = 0
            elif self._looks_like_usb_interface_path(path_text):
                path_kind = 1
            else:
                path_kind = 2
            return (path_kind, interface_key, path_text)

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
            open_paths = self._candidate_open_paths(path)
            if not open_paths:
                attempt_results.append(f"open_path({path_text}) skipped: no usable path")
                continue
            for open_path in open_paths:
                open_path_text = self._fmt_path(open_path)
                try:
                    self._handle.open_path(open_path)
                    return
                except Exception as exc:
                    attempt_results.append(
                        f"open_path({open_path_text}) failed: {type(exc).__name__}: {exc}"
                    )

        try:
            self._handle.open(self.ids.vid, self.ids.pid)
            return
        except Exception as exc:
            attempt_results.append(
                f"open({self.ids.vid:#06x}, {self.ids.pid:#06x}) failed: {type(exc).__name__}: {exc}"
            )
            self._handle = None
            backend = self._hid_backend_metadata(hid)
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
                f"hid backend: {backend}. "
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
