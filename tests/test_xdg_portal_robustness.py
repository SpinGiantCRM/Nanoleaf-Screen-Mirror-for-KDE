import asyncio
import logging
import sys
import types

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
