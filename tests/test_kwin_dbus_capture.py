from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_screenshot2_authorization_error_is_actionable(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)
    monkeypatch.setattr(
        "nanoleaf_sync.capture.kwin_dbus.launch_context_snapshot",
        lambda: {
            "DESKTOP_STARTUP_ID": "startup-secret-token",
            "XDG_ACTIVATION_TOKEN": "activation-secret-token",
        },
    )

    class _Reply:
        error_name = "org.freedesktop.DBus.Error.AccessDenied"
        body = ["not authorized"]

    with pytest.raises(KWinDBusCaptureError, match="cannot associate this process") as exc_info:
        backend._raise_screenshot2_error(_Reply())
    message = str(exc_info.value)
    assert "startup-secret-token" not in message
    assert "activation-secret-token" not in message
    assert "star…oken" in message
    assert "acti…oken" in message


def test_screenshot2_noauthorized_error_is_actionable() -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    class _Reply:
        error_name = "org.kde.KWin.ScreenShot2.Error.NoAuthorized"
        body = ["NoAuthorized"]

    with pytest.raises(KWinDBusCaptureError, match="Qt desktop file name"):
        backend._raise_screenshot2_error(_Reply())


def test_capture_reports_missing_interfaces_from_all_paths(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    async def _s2_fail():
        raise RuntimeError("no ScreenShot2")

    async def _legacy_fail():
        raise RuntimeError("no legacy")

    monkeypatch.setattr(backend, "_capture_reply_via_screenshot2", _s2_fail)
    monkeypatch.setattr(backend, "_capture_reply_via_legacy_interfaces", _legacy_fail)

    with pytest.raises(KWinDBusCaptureError, match="No usable KWin screenshot API"):
        backend._run_async(backend._capture_reply_via_dbus())


def test_capture_reports_signature_mismatch_for_screenshot2(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    async def _s2_fail():
        raise RuntimeError("org.freedesktop.DBus.Error.InvalidArgs")

    async def _legacy_fail():
        raise RuntimeError("org.freedesktop.DBus.Error.UnknownMethod")

    monkeypatch.setattr(backend, "_capture_reply_via_screenshot2", _s2_fail)
    monkeypatch.setattr(backend, "_capture_reply_via_legacy_interfaces", _legacy_fail)

    with pytest.raises(KWinDBusCaptureError, match="No usable KWin screenshot API"):
        backend._run_async(backend._capture_reply_via_dbus())


def test_capture_reuses_single_screenshot2_connection_across_frames(
    tmp_path: Path, monkeypatch
) -> None:
    ppm_path = tmp_path / "frame.ppm"
    ppm_path.write_bytes(b"P6\n2 1\n255\n" + bytes([101, 120, 130, 140, 150, 160]))

    backend = KWinDBusScreenshotCapture(width=2, height=1)
    calls = {"connect": 0}

    async def _fake_connect_screenshot2_bus():
        calls["connect"] += 1
        return object()

    async def _fake_capture_screenshot2():
        await backend._get_screenshot2_bus()
        return str(ppm_path)

    async def _fake_capture_legacy():
        raise RuntimeError("legacy should not be used")

    monkeypatch.setattr(backend, "_connect_screenshot2_bus", _fake_connect_screenshot2_bus)
    monkeypatch.setattr(backend, "_capture_reply_via_screenshot2", _fake_capture_screenshot2)
    monkeypatch.setattr(backend, "_capture_reply_via_legacy_interfaces", _fake_capture_legacy)

    first = backend.capture()
    second = backend.capture()

    assert first.shape == (1, 2, 3)
    assert second.shape == (1, 2, 3)
    assert calls["connect"] == 1
    backend.close()


def test_screenshot2_introspection_is_cached(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)
    calls = {"introspect": 0}

    class _FakeBus:
        async def introspect(self, _bus_name, _path):
            calls["introspect"] += 1
            return object()

    async def _fake_connect():
        return _FakeBus()

    monkeypatch.setattr(backend, "_connect_screenshot2_bus", _fake_connect)

    backend._run_async(backend._get_screenshot2_introspection())
    backend._run_async(backend._get_screenshot2_introspection())

    assert calls["introspect"] == 1
    backend.close()


def test_capture_reconnects_and_retries_after_disconnect_error(tmp_path: Path, monkeypatch) -> None:
    ppm_path = tmp_path / "retry.ppm"
    ppm_path.write_bytes(b"P6\n1 1\n255\n" + bytes([200, 100, 50]))

    backend = KWinDBusScreenshotCapture(width=1, height=1)
    calls = {"s2": 0, "reset": 0}

    async def _fake_screenshot2():
        calls["s2"] += 1
        if calls["s2"] == 1:
            raise RuntimeError("org.freedesktop.DBus.Error.Disconnected")
        return str(ppm_path)

    async def _fake_legacy():
        raise RuntimeError("legacy should not be used")

    original_reset = backend._reset_bus_connections

    async def _tracking_reset():
        calls["reset"] += 1
        await original_reset()

    monkeypatch.setattr(backend, "_capture_reply_via_screenshot2", _fake_screenshot2)
    monkeypatch.setattr(backend, "_capture_reply_via_legacy_interfaces", _fake_legacy)
    monkeypatch.setattr(backend, "_reset_bus_connections", _tracking_reset)

    frame = backend.capture()

    assert frame.shape == (1, 1, 3)
    assert calls["s2"] == 2
    assert calls["reset"] == 1
    backend.close()


def test_reconnect_retry_uses_short_pacing_delay(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=1, height=1)
    calls = {"attempts": 0, "slept": []}

    async def _flaky():
        calls["attempts"] += 1
        if calls["attempts"] == 1:
            raise RuntimeError("org.freedesktop.DBus.Error.NoReply")
        return "ok"

    async def _fake_sleep(delay: float) -> None:
        calls["slept"].append(delay)

    async def _fake_reset() -> None:
        return None

    monkeypatch.setattr(backend, "_reset_bus_connections", _fake_reset)
    monkeypatch.setattr("nanoleaf_sync.capture.kwin_dbus.asyncio.sleep", _fake_sleep)

    result = backend._run_async(backend._call_with_reconnect(_flaky))

    assert result == "ok"
    assert calls["attempts"] == 2
    assert calls["slept"] == [backend._RECONNECT_RETRY_DELAY_SECONDS]
    backend.close()


def test_kwin_backend_applies_hdr_conversion_when_configured(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(
        width=2,
        height=1,
        hdr_max_nits=1200.0,
        hdr_transfer="pq",
        hdr_primaries="bt2020",
    )
    source = np.zeros((1, 2, 3), dtype=np.uint16)
    monkeypatch.setattr(backend, "_try_capture_via_dbus", lambda: source)

    captured: dict[str, object] = {}

    def _fake_convert(frame: np.ndarray, metadata):
        captured["shape"] = frame.shape
        captured["metadata"] = metadata
        return np.ones((1, 2, 3), dtype=np.uint8) * 9

    monkeypatch.setattr("nanoleaf_sync.capture.kwin_dbus.convert_frame_to_srgb8", _fake_convert)

    frame = backend.capture()

    assert frame.dtype == np.uint8
    assert frame.shape == (1, 2, 3)
    assert int(frame[0, 0, 0]) == 9
    assert captured["shape"] == (1, 2, 3)
    meta = captured["metadata"]
    assert getattr(meta, "transfer") == "pq"
    assert getattr(meta, "primaries") == "bt2020"
    assert float(getattr(meta, "max_nits")) == 1200.0


def test_screenshot2_attempts_capture_screen_before_capture_area_with_monitor_id() -> None:
    backend = KWinDBusScreenshotCapture(width=480, height=270, monitor_id="DP-1")

    attempts = backend._screenshot2_method_attempts()

    assert attempts[0][0] == "CaptureScreen"
    assert attempts[1][0] == "CaptureScreen"
    assert len(attempts) == 2
    backend.close()


def test_screenshot2_attempts_capture_area_when_monitor_id_is_not_set() -> None:
    backend = KWinDBusScreenshotCapture(width=480, height=270, monitor_id=None)

    attempts = backend._screenshot2_method_attempts()

    assert attempts[0][0] == "CaptureArea"
    assert attempts[1][0] == "CaptureScreen"
    assert len(attempts) == 2
    backend.close()


def test_ensure_background_loop_waits_outside_lock(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    class _FakeLock:
        def __init__(self) -> None:
            self.held = False

        def __enter__(self):
            self.held = True
            return self

        def __exit__(self, exc_type, exc, tb):
            self.held = False

    class _FakeReady:
        def __init__(self, lock: _FakeLock) -> None:
            self.lock = lock
            self.called_while_held = False

        def clear(self) -> None:
            return None

        def set(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> bool:
            self.called_while_held = self.lock.held
            backend._loop = SimpleNamespace(is_running=lambda: True)
            return True

    fake_lock = _FakeLock()
    fake_ready = _FakeReady(fake_lock)

    class _FakeThread:
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            return None

    monkeypatch.setattr(backend, "_loop_lock", fake_lock)
    monkeypatch.setattr(backend, "_loop_ready", fake_ready)
    monkeypatch.setattr("nanoleaf_sync.capture.kwin_dbus.threading.Thread", _FakeThread)

    loop = backend._ensure_background_loop()

    assert loop is not None
    assert fake_ready.called_while_held is False


def test_read_fd_exact_uses_read_all_when_expected_size_is_none(monkeypatch) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)
    monkeypatch.setattr(backend, "_read_all_bytes_from_fd", lambda _fd: b"fallback-bytes")

    result = backend._read_fd_exact(123, None)

    assert result == b"fallback-bytes"


def test_read_fd_exact_rejects_zero_expected_size_with_context() -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    with pytest.raises(KWinDBusCaptureError, match="zero expected bytes") as exc_info:
        backend._read_fd_exact(123, 0, stride=16, height=9)

    message = str(exc_info.value)
    assert "stride=16" in message
    assert "height=9" in message
    assert "expected_bytes=0" in message


def test_read_fd_exact_rejects_negative_expected_size_with_context() -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    with pytest.raises(KWinDBusCaptureError, match="negative expected byte count") as exc_info:
        backend._read_fd_exact(123, -4, stride=8, height=-1)

    message = str(exc_info.value)
    assert "stride=8" in message
    assert "height=-1" in message
    assert "expected_bytes=-4" in message


def test_screenshot2_zero_stride_metadata_raises_zero_expected_bytes_diagnostic(
    monkeypatch,
) -> None:
    backend = KWinDBusScreenshotCapture(width=2, height=1)

    class _FakeMessage:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_dbus_next = SimpleNamespace(
        Message=_FakeMessage,
        MessageType=SimpleNamespace(ERROR="error"),
    )
    monkeypatch.setitem(sys.modules, "dbus_next", fake_dbus_next)

    class _FakeBus:
        async def call(self, _msg):
            return SimpleNamespace(
                message_type="method_return",
                body=[{"stride": 0, "height": 9}],
            )

    async def _fake_get_bus():
        return _FakeBus()

    async def _fake_get_introspection():
        return object()

    monkeypatch.setattr(backend, "_get_screenshot2_bus", _fake_get_bus)
    monkeypatch.setattr(backend, "_get_screenshot2_introspection", _fake_get_introspection)
    monkeypatch.setattr(
        backend,
        "_screenshot2_method_attempts",
        lambda: [("CaptureArea", "a{sv}h", [0, 0, 2, 1, {}])],
    )

    with pytest.raises(KWinDBusCaptureError, match="zero expected bytes") as exc_info:
        backend._run_async(backend._capture_reply_via_screenshot2())

    message = str(exc_info.value)
    assert "stride=0" in message
    assert "height=9" in message
    assert "expected_bytes=0" in message
