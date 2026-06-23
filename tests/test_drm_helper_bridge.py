from __future__ import annotations

import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from nanoleaf_sync.capture import _drm_helper_bridge as bridge


def test_request_helper_mmap_parses_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "nanoleaf_drm_helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setattr(bridge, "_helper_binary_path", lambda: helper)
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

    class _FakeProc:
        returncode = 0

        def poll(self) -> int | None:
            return None

        def communicate(self, timeout: float = 0) -> tuple[str, str]:
            return "", ""

    def _popen(args, **_kwargs):
        sent["args"] = args
        sock_path = str(args[2])
        pass_fd, _peer_fd = socket.socketpair()

        def _client() -> None:
            time.sleep(0.05)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(sock_path)
                client.sendall(payload)
                client.sendmsg(
                    [b"\x00"],
                    [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", pass_fd.fileno()))],
                )
            finally:
                client.close()
                pass_fd.close()

        threading.Thread(target=_client, daemon=True).start()
        return _FakeProc()

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
