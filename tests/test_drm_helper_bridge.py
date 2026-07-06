from __future__ import annotations

import struct
from pathlib import Path

import pytest

from nanoleaf_sync.capture import _drm_helper_bridge as bridge


def test_request_helper_mmap_parses_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "nanoleaf_drm_helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setattr(bridge, "_helper_binary_path", lambda: helper)
    monkeypatch.setattr(bridge, "_helper_launch_allowed", lambda _helper: True)
    monkeypatch.setattr(bridge.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(bridge.os, "getpid", lambda: 999)

    modifier = (0x03 << 56) | 0x10
    payload = struct.pack(
        "=QQIIIIIII",
        16,
        4096,
        7680,
        0x34324258,
        42,
        1920,
        1080,
        modifier & 0xFFFFFFFF,
        modifier >> 32,
    )
    sent: dict[str, object] = {}
    server_state: dict[str, object] = {}

    class _FakeServer:
        def bind(self, path: str) -> None:
            server_state["bound_path"] = path

        def listen(self, backlog: int) -> None:
            server_state["listen_backlog"] = backlog

        def settimeout(self, timeout: float) -> None:
            server_state["timeout"] = timeout

        def close(self) -> None:
            server_state["closed"] = True

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            server_state["conn_closed"] = True

    class _FakeProc:
        returncode = 0

        def poll(self) -> int | None:
            return None

        def communicate(self, timeout: float = 0) -> tuple[str, str]:
            return "", ""

    def _popen(args, **_kwargs):
        sent["args"] = args
        return _FakeProc()

    monkeypatch.setattr(bridge.socket, "socket", lambda *_args, **_kwargs: _FakeServer())
    monkeypatch.setattr(bridge, "_accept_helper_connection", lambda _server, _proc: _FakeConn())
    monkeypatch.setattr(bridge, "_recv_payload_with_fds", lambda _conn, _size: (payload, [123]))
    monkeypatch.setattr(bridge.subprocess, "Popen", _popen)
    monkeypatch.setattr(bridge, "_fd_is_dma_buf", lambda _fd: True)

    info = bridge.request_helper_mmap(card_path="/dev/dri/card0", fb_id=0)

    assert info is not None
    assert info.fb_id == 42
    assert info.pitch == 7680
    assert info.fourcc == 0x34324258
    assert info.size == 4096
    assert info.offset == 16
    assert info.width == 1920
    assert info.height == 1080
    assert info.modifier == modifier
    assert info.is_dma_buf is True
    assert sent["args"] == [
        str(helper),
        "/dev/dri/card0",
        f"{tmp_path}/nanoleaf_drm_999_0.sock",
        "0",
    ]
    assert server_state["bound_path"] == f"{tmp_path}/nanoleaf_drm_999_0.sock"
    assert server_state["listen_backlog"] == 1
    assert server_state["closed"] is True
    assert server_state["conn_closed"] is True
