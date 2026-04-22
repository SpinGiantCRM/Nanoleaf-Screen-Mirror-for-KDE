from __future__ import annotations

import sys
import types

import pytest

from nanoleaf_sync.device.hid_transport import HIDTransport
from nanoleaf_sync.device.interfaces import NanoleafUSBIds


class FakeHIDHandle:
    def __init__(self, reads: list[bytes]) -> None:
        self.reads = list(reads)
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)

    def read(self, _size: int, _timeout_ms: int):
        if not self.reads:
            return []
        return list(self.reads.pop(0))

    def close(self) -> None:
        return None


class _FailingOpenHandle(FakeHIDHandle):
    def __init__(self) -> None:
        super().__init__(reads=[])

    def open(self, _vid: int, _pid: int) -> None:
        raise OSError("access denied")


class _PathAwareHandle(FakeHIDHandle):
    def __init__(self, *, fail_paths: set[bytes] | None = None) -> None:
        super().__init__(reads=[])
        self.fail_paths = fail_paths or set()
        self.opened_path: bytes | None = None
        self.opened_vidpid: tuple[int, int] | None = None

    def open_path(self, path: bytes) -> None:
        if path in self.fail_paths:
            raise OSError("busy")
        self.opened_path = path

    def open(self, vid: int, pid: int) -> None:
        self.opened_vidpid = (vid, pid)


def test_transceive_round_trip_with_report_id_prefix() -> None:
    # response TLV: type=0x83, len=3, payload=00 00 0A
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0A" + b"\x00" * 58])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0A"
    assert fake.writes
    assert fake.writes[0][0] == 0
    assert fake.writes[0][1:4] == b"\x03\x00\x00"


def test_transceive_multi_read_accumulates_full_tlv() -> None:
    fake = FakeHIDHandle([
        b"\x00\x8C\x00\x07\x00NL",
        b"\x00" + b"82K2" + b"\x00" * 59,
    ])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response = transport.transceive(b"\x0C\x00\x00")

    assert response == b"\x8C\x00\x07\x00NL82K2"


def test_transceive_accepts_no_report_id_prefix_when_enabled_by_default() -> None:
    # Device replies with no report-id prefix (64-byte packet starts with TLV type directly).
    fake = FakeHIDHandle([b"\x83\x00\x03\x00\x00\x0A" + b"\x00" * 58])
    transport = HIDTransport(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        report_size=64,
        use_report_id_prefix=True,
    )
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0A"


def test_transceive_accepts_prefixed_reply_when_prefix_disabled() -> None:
    # Compatibility fallback: read framing may still include a report-id byte.
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0A" + b"\x00" * 58])
    transport = HIDTransport(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        report_size=64,
        use_report_id_prefix=False,
    )
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0A"


def test_transceive_times_out_on_empty_read() -> None:
    fake = FakeHIDHandle([])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    with pytest.raises(RuntimeError, match="Timed out"):
        transport.transceive(b"\x03\x00\x00")


def test_transceive_raises_on_malformed_continuous_data() -> None:
    class _InfiniteMalformedHandle(FakeHIDHandle):
        def __init__(self) -> None:
            super().__init__(reads=[])
            self._chunk = b"\x00\x99\x00\x01\xFF" + b"\x00" * 59

        def read(self, _size: int, _timeout_ms: int):
            return list(self._chunk)

    fake = _InfiniteMalformedHandle()
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    with pytest.raises(RuntimeError, match="Malformed HID response"):
        transport.transceive(b"\x03\x00\x00")


def test_open_wraps_hid_permission_error_with_actionable_message(monkeypatch) -> None:
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [object()],
        device=lambda: _FailingOpenHandle(),
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)

    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError, match="Attempt results"):
        transport.open()


def test_open_prefers_enumerated_path_before_vid_pid(monkeypatch) -> None:
    handle = _PathAwareHandle()
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [{"path": b"/dev/hidraw3", "interface_number": 0}],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open()
    assert handle.opened_path == b"/dev/hidraw3"
    assert handle.opened_vidpid is None


def test_open_uses_vid_pid_fallback_when_all_paths_fail(monkeypatch) -> None:
    handle = _PathAwareHandle(fail_paths={b"/dev/hidraw3"})
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [{"path": b"/dev/hidraw3", "interface_number": 1}],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open()
    assert handle.opened_path is None
    assert handle.opened_vidpid == (0x37FA, 0x8202)
