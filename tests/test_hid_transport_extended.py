"""Tests for device/hid_transport.py retry logic, error paths, and write methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanoleaf_sync.device.hid_transport import HIDTransport
from nanoleaf_sync.device.interfaces import NanoleafUSBIds

# ---------------------------------------------------------------------------
# open() retry logic
# ---------------------------------------------------------------------------


def test_open_retry_no_devices_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no devices are found after retries, raises RuntimeError."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)

    import sys

    fake_hid = MagicMock()
    fake_hid.enumerate.return_value = []
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)

    with pytest.raises(RuntimeError, match="Nanoleaf device not found"):
        transport.open(retry_attempts=2, retry_delay_s=0.01)


def test_open_retry_zero_attempts_no_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """With retry_attempts=0, tries once and fails."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)

    import sys

    fake_hid = MagicMock()
    fake_hid.enumerate.return_value = []
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)

    with pytest.raises(RuntimeError, match="Nanoleaf device not found"):
        transport.open(retry_attempts=0, retry_delay_s=0.01)


def test_open_retries_when_device_is_busy_then_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Busy open failures should retry the full enumerate+open path."""
    import sys
    import types

    class _BusyThenOpenHandle:
        def __init__(self) -> None:
            self.open_attempts = 0
            self.opened_path: bytes | None = None

        def open_path(self, path: bytes) -> None:
            self.open_attempts += 1
            if self.open_attempts == 1:
                raise OSError("busy")
            self.opened_path = path

        def open(self, _vid: int, _pid: int) -> None:
            raise OSError("open failed")

        def close(self) -> None:
            return None

    handle = _BusyThenOpenHandle()
    fake_hid = types.SimpleNamespace(
        __file__="/tmp/fake-hid.so",
        __version__="0.15.0",
        enumerate=lambda _vid, _pid: [{"path": b"/dev/hidraw0", "interface_number": 0}],
        device=lambda: handle,
    )
    monkeypatch.setitem(sys.modules, "hid", fake_hid)
    monkeypatch.setitem(sys.modules, "hidraw", fake_hid)
    monkeypatch.setattr(
        HIDTransport,
        "_linux_hidraw_candidates_for_ids",
        lambda *_args, **_kwargs: [],
    )

    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.open(retry_attempts=1, retry_delay_s=0.01)

    assert handle.opened_path == b"/dev/hidraw0"
    assert handle.open_attempts == 2


def test_open_hid_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """When hid module cannot be imported, RuntimeError propagates (wrapping the import failure)."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)

    import sys

    # Remove hid from sys.modules so import is attempted fresh
    monkeypatch.delitem(sys.modules, "hid", raising=False)

    import builtins

    original_import = builtins.__import__

    def _fail_hid_and_hidraw(name, *args, **kwargs):
        if name in ("hid", "hidraw"):
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_hid_and_hidraw)

    with pytest.raises(RuntimeError, match="HID bindings not installed"):
        transport.open()


# ---------------------------------------------------------------------------
# write / write_with_timing
# ---------------------------------------------------------------------------


def test_write_not_opened() -> None:
    """Writing without opening raises RuntimeError."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError):
        transport.write(b"\x01\x02\x03")


def test_write_with_timing_not_opened() -> None:
    """write_with_timing without opening raises RuntimeError."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError):
        transport.write_with_timing(b"\x01\x02\x03")


def test_write_with_nonblocking_drain_not_opened() -> None:
    """write_with_nonblocking_drain without opening raises RuntimeError."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError):
        transport.write_with_nonblocking_drain(b"\x01\x02\x03")


def test_transceive_with_timing_not_opened() -> None:
    """transceive_with_timing without opening should error."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError):
        transport.transceive_with_timing(b"\x01\x02\x03")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_not_opened() -> None:
    """Closing when not opened should not crash."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    transport.close()  # Should not raise


def test_close_after_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing after opening should call close on the handle."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)

    fake_handle = MagicMock()
    transport._handle = fake_handle

    transport.close()
    fake_handle.close.assert_called_once()
    assert transport._handle is None


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_not_opened() -> None:
    """Reading without opening raises RuntimeError."""
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    with pytest.raises(RuntimeError, match="not opened"):
        transport.read()


# ---------------------------------------------------------------------------
# HIDTransport construction
# ---------------------------------------------------------------------------


def test_transport_default_values() -> None:
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    assert transport.ids.vid == 0x37FA
    assert transport.ids.pid == 0x8202
    assert transport.report_size == 64
    assert transport._handle is None


def test_transport_with_custom_timeout() -> None:
    transport = HIDTransport(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        report_size=64,
        read_timeout_ms=100,
    )
    assert transport.read_timeout_ms == 100


def test_transport_use_report_id_prefix_default() -> None:
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    assert transport.use_report_id_prefix is True
