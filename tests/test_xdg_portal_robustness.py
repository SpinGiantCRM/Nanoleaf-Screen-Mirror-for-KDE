import asyncio
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
