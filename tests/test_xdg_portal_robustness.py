import asyncio
import types

import numpy as np
import pytest

from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture, XDGPortalError


class _FakeBusNoUniqueName:
    unique_name = None

    async def connect(self):
        return self


def test_negotiate_portal_fails_cleanly_without_unique_name(monkeypatch) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda **_kwargs: _FakeBusNoUniqueName())

    backend = XDGPortalCapture(width=4, height=4)

    with pytest.raises(XDGPortalError, match="unique name is unavailable"):
        asyncio.run(backend._negotiate_portal())


def test_close_pipewire_stream_stops_gstreamer_pipeline(monkeypatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    backend._use_gstreamer = True
    calls: list[str] = []

    class _FakePipeline:
        def set_state(self, _state) -> None:
            calls.append("null")

    backend._gst_pipeline = _FakePipeline()

    class _FakeGst:
        class State:
            NULL = object()

    import sys

    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gst=_FakeGst))

    backend._close_pipewire_stream()

    assert calls == ["null"]
    assert backend._gst_pipeline is None
    assert backend._gst_sink is None


def test_open_pipewire_stream_falls_back_when_binding_symbols_missing(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    calls: list[tuple[int, int]] = []

    class _FakePipewire:
        MainLoop = object
        Context = object
        Stream = object
        Direction = object
        StreamFlags = object

    def _fake_open_via_gstreamer(fd: int, node_id: int) -> None:
        calls.append((fd, node_id))

    import sys

    monkeypatch.setitem(sys.modules, "pipewire", _FakePipewire())
    monkeypatch.setattr(backend, "_open_via_gstreamer", _fake_open_via_gstreamer)

    with caplog.at_level("INFO"):
        backend._open_pipewire_stream(fd=11, node_id=22)

    assert calls == [(11, 22)]
    assert "unsupported" in caplog.text
    assert "SpaPod" in caplog.text


def test_read_frame_gstreamer_returns_none_without_sink() -> None:
    backend = XDGPortalCapture(width=2, height=2)
    backend._use_gstreamer = True
    assert backend._read_frame_gstreamer() is None


def test_mapped_bytes_to_rgb_handles_bgrx_and_stride_padding() -> None:
    backend = XDGPortalCapture(width=2, height=1)
    # Two pixels in BGRx with 4 bytes of row padding
    payload = bytes([
        10, 20, 30, 0,
        40, 50, 60, 0,
        0, 0, 0, 0,
    ])
    frame = backend._mapped_bytes_to_rgb(
        payload=payload,
        width=2,
        height=1,
        fmt="BGRx",
        stride=12,
    )
    assert frame is not None
    assert frame.shape == (1, 2, 3)
    # Converted RGB
    assert frame[0, 0].tolist() == [30, 20, 10]
    assert frame[0, 1].tolist() == [60, 50, 40]


@pytest.mark.parametrize("fmt", ["RGB", "BGR", "RGBx", "BGRx", "RGBA", "BGRA"])
def test_mapped_bytes_to_rgb_supports_multiple_formats(fmt: str) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    if fmt in {"RGB", "BGR"}:
        payload = bytes([1, 2, 3])
    else:
        payload = bytes([1, 2, 3, 255])
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (1, 1, 3)


def test_explicit_diagnostic_reports_zero_byte_buffer_details(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)

    monkeypatch.setattr(backend, "initialize", lambda: None)
    monkeypatch.setattr(backend, "close", lambda: None)

    def _capture() -> np.ndarray:
        backend._last_frame_diag = {
            "sample_received": True,
            "buffer_present": True,
            "buffer_reported_size": 0,
            "memory_count": 1,
            "mapped_memory_size": 0,
            "caps": "video/x-raw,format=RGB,width=2,height=2",
            "width": 2,
            "height": 2,
            "format": "RGB",
            "framerate": "30/1",
            "stride": 6,
            "pts_ns": 100,
            "dts_ns": 90,
            "duration_ns": 33_000_000,
            "empty_buffer_count": 3,
            "non_empty_buffer_count": 0,
        }
        return np.zeros((0,), dtype=np.uint8)

    monkeypatch.setattr(backend, "capture", _capture)

    result = backend.run_explicit_diagnostic()
    assert result["status"] == "failed"
    details = result["details"]
    assert details["sample_received"] is True
    assert details["buffer_present"] is True
    assert details["buffer_reported_size"] == 0
    assert details["mapped_memory_size"] == 0
    assert details["empty_buffer_count"] == 3


def test_explicit_diagnostic_returns_staged_failure(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)

    def _boom() -> None:
        raise XDGPortalError("OpenPipeWireRemote failed: synthetic")

    monkeypatch.setattr(backend, "initialize", _boom)
    monkeypatch.setattr(backend, "close", lambda: None)

    result = backend.run_explicit_diagnostic()
    assert result["status"] == "failed"
    assert result["mode"] == "explicit-test"
    assert result["failing_stage"] == "PipeWire node/stream received"
    assert isinstance(result["stages"], list)
