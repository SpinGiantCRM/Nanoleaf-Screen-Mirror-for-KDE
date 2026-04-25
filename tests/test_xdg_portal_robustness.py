import asyncio
import logging
import sys
import types
from pathlib import Path

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


class _FakeProc:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:  # pragma: no cover - trivial
        raise TimeoutError("synthetic wait timeout")

    def kill(self) -> None:
        self.killed = True


class _FakeMMap:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_close_pipewire_stream_kills_stuck_gstreamer_process(monkeypatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    backend._use_gstreamer = True
    backend._gst_proc = _FakeProc()
    backend._shm_mm = _FakeMMap()
    backend._shm_file = types.SimpleNamespace(name="/tmp/fake-portal-frame.raw")

    unlinked: list[str] = []
    monkeypatch.setattr("os.unlink", lambda path: unlinked.append(path))

    backend._close_pipewire_stream()

    assert backend._gst_proc.terminated is True
    assert backend._gst_proc.killed is True
    assert backend._shm_mm.closed is True
    assert unlinked == ["/tmp/fake-portal-frame.raw"]


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

    monkeypatch.setitem(sys.modules, "pipewire", _FakePipewire())
    monkeypatch.setattr(backend, "_open_via_gstreamer", _fake_open_via_gstreamer)

    with caplog.at_level(logging.INFO):
        backend._open_pipewire_stream(fd=11, node_id=22)

    assert calls == [(11, 22)]
    assert "unsupported" in caplog.text
    assert "SpaPod" in caplog.text


def test_open_pipewire_stream_falls_back_on_pipewire_attribute_error(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    calls: list[tuple[int, int]] = []

    def _raise_attr_error(_fd: int, _node_id: int) -> None:
        raise AttributeError("synthetic missing attribute")

    def _fake_open_via_gstreamer(fd: int, node_id: int) -> None:
        calls.append((fd, node_id))

    monkeypatch.setattr(backend, "_pipewire_python_is_supported", lambda: (True, "supported"))
    monkeypatch.setattr(backend, "_open_via_pipewire_python", _raise_attr_error)
    monkeypatch.setattr(backend, "_open_via_gstreamer", _fake_open_via_gstreamer)

    with caplog.at_level(logging.WARNING):
        backend._open_pipewire_stream(fd=33, node_id=44)

    assert calls == [(33, 44)]
    assert "falling back to GStreamer" in caplog.text


class _FakeReadableMMap:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def seek(self, _offset: int) -> None:
        return

    def read(self, size: int) -> bytes:
        return self._payload[:size]


def test_read_frame_gstreamer_waits_for_first_frame_then_returns_array(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)
    backend._frame_bytes = 12
    backend._shm_file = types.SimpleNamespace(name="/tmp/fake.raw")
    backend._shm_mm = _FakeReadableMMap(bytes(range(12)))
    backend._first_frame_ready = False
    backend._first_frame_deadline_s = 0.1
    backend._first_frame_poll_interval_s = 0.0
    backend._shm_initial_mtime_ns = 100

    stats = iter(
        [
            types.SimpleNamespace(st_size=12, st_mtime_ns=100),
            types.SimpleNamespace(st_size=12, st_mtime_ns=101),
        ]
    )
    monotonic_values = iter([0.0, 0.01, 0.02, 0.03])

    monkeypatch.setattr("os.stat", lambda _path: next(stats))
    monkeypatch.setattr("time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    frame = backend._read_frame_gstreamer()

    assert frame is not None
    assert frame.shape == (2, 2, 3)
    assert backend._first_frame_ready is True


def test_read_frame_gstreamer_raises_clear_error_on_cold_start_timeout(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)
    backend._frame_bytes = 12
    backend._shm_file = types.SimpleNamespace(name=str(Path("/tmp/fake.raw")))
    backend._shm_mm = _FakeReadableMMap(b"")
    backend._first_frame_ready = False
    backend._first_frame_deadline_s = 0.01
    backend._first_frame_poll_interval_s = 0.0
    backend._shm_initial_mtime_ns = 100

    monotonic_values = iter([0.0, 0.005, 0.02])
    monkeypatch.setattr(
        "os.stat",
        lambda _path: types.SimpleNamespace(st_size=0, st_mtime_ns=100),
    )
    monkeypatch.setattr("time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(XDGPortalError, match="timed out waiting for first frame bytes"):
        backend._read_frame_gstreamer()


def test_read_frame_gstreamer_reports_repeated_empty_buffers(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)
    backend._frame_bytes = 12
    backend._shm_file = types.SimpleNamespace(name=str(Path("/tmp/fake.raw")))
    backend._shm_mm = _FakeReadableMMap(b"")
    backend._first_frame_ready = False
    backend._first_frame_deadline_s = 0.2
    backend._first_frame_poll_interval_s = 0.0
    backend._shm_initial_mtime_ns = 100
    backend._MAX_EMPTY_FIRST_BUFFERS = 2

    stats = iter(
        [
            types.SimpleNamespace(st_size=12, st_mtime_ns=101),
            types.SimpleNamespace(st_size=12, st_mtime_ns=102),
        ]
    )
    monotonic_values = iter([0.0, 0.01, 0.02, 0.03])
    monkeypatch.setattr("os.stat", lambda _path: next(stats))
    monkeypatch.setattr("time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(XDGPortalError, match="produced empty buffers"):
        backend._read_frame_gstreamer()


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
