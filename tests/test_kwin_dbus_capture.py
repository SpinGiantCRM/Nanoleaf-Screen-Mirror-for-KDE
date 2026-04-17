from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nanoleaf_sync.capture.kwin_dbus import (
    KWinDBusCaptureError,
    KWinDBusScreenshotCapture,
    _ScreenShot2Payload,
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


def test_screenshot2_payload_decodes_raw_metadata(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    seen = {}

    def _fake_decode(*, data: bytes, width: int, height: int, stride: int, image_format: int):
        seen["args"] = (data, width, height, stride, image_format)
        return np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)

    monkeypatch.setattr(backend, "_decode_qimage_raw_frame", _fake_decode)

    payload = _ScreenShot2Payload(
        data=b"\x00" * 8,
        results={
            "type": "raw",
            "width": 2,
            "height": 1,
            "stride": 8,
            "format": 17,
        },
    )

    frame = backend._decode_reply_to_rgb(payload)

    assert frame is not None
    assert frame.shape == (1, 2, 3)
    assert frame.dtype == np.uint8
    assert seen["args"][1:] == (2, 1, 8, 17)


def test_screenshot2_payload_rejects_unsupported_type() -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    with pytest.raises(KWinDBusCaptureError, match="Unsupported KWin ScreenShot2 result type"):
        backend._decode_reply_to_rgb(
            _ScreenShot2Payload(
                data=b"\x00" * 4,
                results={"type": "png", "width": 1, "height": 1, "stride": 4, "format": 17},
            )
        )


def test_screenshot2_authorization_error_is_actionable() -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    class _Reply:
        error_name = "org.freedesktop.DBus.Error.AccessDenied"
        body = ["not authorized"]

    with pytest.raises(KWinDBusCaptureError, match="X-KDE-DBUS-Restricted-Interfaces"):
        backend._raise_screenshot2_error(_Reply())


def test_capture_reports_missing_interfaces_from_all_paths(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    async def _s2_fail():
        raise RuntimeError("no ScreenShot2")

    async def _legacy_fail():
        raise RuntimeError("no legacy")

    monkeypatch.setattr(backend, "_capture_reply_via_screenshot2", _s2_fail)
    monkeypatch.setattr(backend, "_capture_reply_via_legacy_interfaces", _legacy_fail)

    with pytest.raises(KWinDBusCaptureError, match="All known KWin screenshot D-Bus API variants failed"):
        backend._run_async(backend._capture_reply_via_dbus())
