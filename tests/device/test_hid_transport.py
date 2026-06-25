from __future__ import annotations

import sys
import threading
import types

import pytest

from nanoleaf_sync.device.hid_transport import HIDTransport, HIDWriteError
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
        return None

    def open(self, vid: int, pid: int) -> None:
        self.opened_vidpid = (vid, pid)


class _AlwaysFailOpenHandle(_PathAwareHandle):
    def open_path(self, path: bytes) -> None:
        raise OSError("open failed")

    def open(self, vid: int, pid: int) -> None:
        raise OSError("open failed")


def test_transceive_round_trip_with_report_id_prefix() -> None:
    # response TLV: type=0x83, len=3, payload=00 00 0A
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0a"
    assert fake.writes
    assert fake.writes[0][0] == 0
    assert fake.writes[0][1:4] == b"\x03\x00\x00"


def test_write_with_timing_reports_multi_report_metadata() -> None:
    fake = FakeHIDHandle([])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake
    request = b"\x02\x00\x90" + (b"\x01" * 144)

    timing = transport.write_with_timing(request)

    assert timing["report_count"] == 3
    assert timing["bytes_per_report"] == 64
    assert timing["total_frame_bytes"] == len(request)
    assert timing["report_data_sizes"] == [64, 64, 19]
    assert len(timing["per_report_write_ms"]) == 3
    assert timing["write_blocking"] is True
    assert timing["retry_policy"] == "none"
    assert timing["rate_limit_policy"] == "none"


def test_transceive_multi_read_accumulates_full_tlv() -> None:
    fake = FakeHIDHandle(
        [
            b"\x00\x8c\x00\x07\x00NL",
            b"\x00" + b"82K2" + b"\x00" * 59,
        ]
    )
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response = transport.transceive(b"\x0c\x00\x00")

    assert response == b"\x8c\x00\x07\x00NL82K2"


def test_transceive_allows_empty_read_between_response_chunks() -> None:
    fake = FakeHIDHandle(
        [
            b"\x00\x8c\x00\x07\x00NL",
            b"",
            b"\x00" + b"82K2" + b"\x00" * 59,
        ]
    )
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response = transport.transceive(b"\x0c\x00\x00")

    assert response == b"\x8c\x00\x07\x00NL82K2"


def test_transceive_accepts_no_report_id_prefix_when_enabled_by_default() -> None:
    # Device replies with no report-id prefix (64-byte packet starts with TLV type directly).
    fake = FakeHIDHandle([b"\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58])
    transport = HIDTransport(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        report_size=64,
        use_report_id_prefix=True,
    )
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0a"


def test_transceive_accepts_prefixed_reply_when_prefix_disabled() -> None:
    # Compatibility fallback: read framing may still include a report-id byte.
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58])
    transport = HIDTransport(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        report_size=64,
        use_report_id_prefix=False,
    )
    transport._handle = fake

    response = transport.transceive(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0a"


def test_transceive_with_timing_includes_write_and_wait_components() -> None:
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    response, timing = transport.transceive_with_timing(b"\x03\x00\x00")

    assert response == b"\x83\x00\x03\x00\x00\x0a"
    assert timing["report_count"] == 1
    assert timing["total_frame_bytes"] == 3
    assert len(timing["per_report_write_ms"]) == 1
    assert timing["flush_or_wait_ms"] >= 0.0
    assert timing["read_calls"] >= 1


def test_write_with_nonblocking_drain_uses_blocking_ack_then_nonblocking_drain() -> None:
    fake = FakeHIDHandle([b"\x00\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58, b""])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    timing = transport.write_with_nonblocking_drain(b"\x03\x00\x00", max_drain_reads=2)

    assert timing["report_count"] == 1
    assert timing["total_frame_bytes"] == 3
    assert timing["read_calls"] == 1
    assert timing["flush_or_wait_ms"] >= 0.0


def test_write_with_nonblocking_drain_respects_wall_clock_budget() -> None:
    class _AlwaysDataHandle(FakeHIDHandle):
        def read(self, _size: int, _timeout_ms: int):
            return list(b"\x00" * 65)

    fake = _AlwaysDataHandle(reads=[])
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    timing = transport.write_with_nonblocking_drain(
        b"\x03\x00\x00",
        max_drain_reads=64,
        ack_timeout_ms=25,
        drain_budget_ms=8,
    )

    assert timing["read_calls"] >= 1
    assert timing["flush_or_wait_ms"] < 80.0


def test_write_with_nonblocking_drain_phase1_uses_one_ms_poll_loop() -> None:
    class _LateAckHandle(FakeHIDHandle):
        def __init__(self) -> None:
            super().__init__(reads=[])
            self._calls = 0

        def read(self, _size: int, timeout_ms: int):
            self._calls += 1
            assert timeout_ms == 1
            if self._calls >= 20:
                return list(b"\x00\x83\x00\x03\x00\x00\x0a" + b"\x00" * 58)
            return []

    fake = _LateAckHandle()
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    timing = transport.write_with_nonblocking_drain(
        b"\x03\x00\x00",
        ack_timeout_ms=25,
        drain_budget_ms=1,
        max_drain_reads=1,
    )

    assert timing["read_calls"] == 1
    assert float(timing.get("ack_arrival_ms", 0.0)) >= 0.0


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
            self._chunk = b"\x00\x99\x00\x01\xff" + b"\x00" * 59

        def read(self, _size: int, _timeout_ms: int):
            return list(self._chunk)

    fake = _InfiniteMalformedHandle()
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = fake

    with pytest.raises(RuntimeError, match="Malformed HID response"):
        transport.transceive(b"\x03\x00\x00")


def test_open_wraps_hid_permission_error_with_actionable_message(monkeypatch) -> None:
    fake_hid = types.SimpleNamespace(
        __file__="/tmp/fake-hid.so",
        __version__="0.15.0",
        enumerate=lambda _vid, _pid: [object()],
        device=lambda: _FailingOpenHandle(),
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)

    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError, match="hid backend"):
        transport.open()


def test_open_prefers_enumerated_path_before_vid_pid(monkeypatch) -> None:
    handle = _PathAwareHandle()
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [{"path": b"/dev/hidraw3", "interface_number": 0}],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)
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
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open()
    assert handle.opened_path is None
    assert handle.opened_vidpid == (0x37FA, 0x8202)


def test_open_resolves_linux_usb_interface_path_to_hidraw(monkeypatch, tmp_path) -> None:
    usb_interface = "3-1:1.0"
    hidraw_dir = tmp_path / "sys" / "bus" / "usb" / "devices" / usb_interface / "hidraw"
    hidraw_dir.mkdir(parents=True)
    (hidraw_dir / "hidraw7").touch()

    handle = _PathAwareHandle(fail_paths={usb_interface.encode("utf-8")})
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [
            {"path": usb_interface.encode("utf-8"), "interface_number": 0}
        ],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)

    from nanoleaf_sync.device import hid_transport as hid_transport_module

    real_path_cls = hid_transport_module.Path

    def _path_override(first: str, *rest: str):
        if first == "/sys/bus/usb/devices":
            return real_path_cls(tmp_path / "sys" / "bus" / "usb" / "devices", *rest)
        return real_path_cls(first, *rest)

    monkeypatch.setattr(hid_transport_module, "Path", _path_override)

    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open()
    assert handle.opened_path == b"/dev/hidraw7"


def test_open_uses_linux_sysfs_hidraw_mapping_when_enumeration_path_not_openable(
    monkeypatch, tmp_path
) -> None:
    usb_interface = "3-1:1.0"
    sys_class = tmp_path / "sys" / "class" / "hidraw" / "hidraw5" / "device"
    iface_dir = tmp_path / "sys" / "devices" / "pci0000:00" / "0000:00:14.0" / usb_interface
    iface_dir.mkdir(parents=True)
    (iface_dir / "idVendor").write_text("37fa\n", encoding="utf-8")
    (iface_dir / "idProduct").write_text("8202\n", encoding="utf-8")
    (iface_dir / "bInterfaceNumber").write_text("00\n", encoding="utf-8")
    sys_class.parent.mkdir(parents=True)
    sys_class.symlink_to(iface_dir, target_is_directory=True)

    handle = _PathAwareHandle(fail_paths={usb_interface.encode("utf-8")})
    fake_hid = types.SimpleNamespace(
        enumerate=lambda _vid, _pid: [
            {"path": usb_interface.encode("utf-8"), "interface_number": 0}
        ],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)

    from nanoleaf_sync.device import hid_transport as hid_transport_module

    real_path_cls = hid_transport_module.Path

    def _path_override(first: str, *rest: str):
        if first == "/sys/bus/usb/devices":
            return real_path_cls(tmp_path / "sys" / "bus" / "usb" / "devices", *rest)
        if first == "/sys/class/hidraw":
            return real_path_cls(tmp_path / "sys" / "class" / "hidraw", *rest)
        return real_path_cls(first, *rest)

    monkeypatch.setattr(hid_transport_module, "Path", _path_override)

    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open()
    assert handle.opened_path == b"/dev/hidraw5"


def test_open_error_reports_unusable_candidate_path_format(monkeypatch) -> None:
    handle = _AlwaysFailOpenHandle()
    fake_hid = types.SimpleNamespace(
        __file__="/tmp/fake-hid.so",
        __version__="0.15.0",
        enumerate=lambda _vid, _pid: [{"path": b"3-1:1.0", "interface_number": 0}],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError, match="candidate path format is not directly openable"):
        transport.open()


class _BlockingHIDWriteHandle:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._block = threading.Event()

    def write(self, data: bytes) -> int:
        self._block.wait()
        self.writes.append(bytes(data))
        return len(data)

    def read(self, _size: int, _timeout_ms: int) -> list[int]:
        return []

    def close(self) -> None:
        self._block.set()


def test_write_payload_timeout_raises_on_blocking_handle() -> None:
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport._handle = _BlockingHIDWriteHandle()
    payload = b"\x00" * 64
    with pytest.raises(HIDWriteError, match="timed out"):
        transport._write_payload(payload, write_timeout_ms=50)
