from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nanoleaf_sync.capture.kwin_dbus import (
    KWinDBusCaptureError,
    KWinDBusScreenshotCapture,
)


async def _return(value):
    return value


async def _raise(exc: Exception):
    raise exc


def test_kwin_dbus_decodes_file_payload_to_rgb(tmp_path: Path, monkeypatch) -> None:
    ppm_path = tmp_path / "shot.ppm"
    ppm_path.write_bytes(b"P6\n2 1\n255\n" + bytes([255, 0, 0, 0, 255, 0]))

    backend = KWinDBusScreenshotCapture(width=2, height=1)
    monkeypatch.setattr(backend, "_capture_reply_via_dbus", lambda: _return(str(ppm_path)))

    frame = backend.capture()

    assert frame.shape == (1, 2, 3)
    assert frame.dtype == np.uint8
    assert tuple(frame[0, 0].tolist()) == (255, 0, 0)
    assert tuple(frame[0, 1].tolist()) == (0, 255, 0)


def test_kwin_dbus_capture_raises_clear_error_on_failure(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=4, height=3)
    monkeypatch.setattr(
        backend,
        "_capture_reply_via_dbus",
        lambda: _raise(RuntimeError("session bus offline")),
    )

    with pytest.raises(KWinDBusCaptureError, match="KWin D-Bus screenshot failed"):
        backend.capture()
