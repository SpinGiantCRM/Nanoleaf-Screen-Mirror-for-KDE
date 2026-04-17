from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class KWinDBusCaptureParams:
    width: int
    height: int
    # If None, the implementation will use the primary screen.
    # Monitor selection is intentionally left flexible because KDE/KWin
    # export different identifiers depending on version/compositor.
    monitor_id: Optional[str] = None


class KWinDBusCaptureError(RuntimeError):
    """Raised when KWin D-Bus screenshot capture is unavailable or fails."""


class KWinDBusScreenshotCapture:
    """KWin D-Bus screenshot capture backend."""

    name = "kwin-dbus"

    _API_CANDIDATES = (
        # KDE Plasma interface variants seen across versions/distributions.
        ("org.kde.KWin", "/Screenshot", "org.kde.kwin.Screenshot"),
        ("org.kde.KWin", "/org/kde/KWin/Screenshot", "org.kde.kwin.Screenshot"),
    )

    _METHOD_CANDIDATES = (
        "screenshotFullscreen",
        "captureScreen",
        "screenshotScreen",
    )

    def __init__(
        self, width: int, height: int, monitor_id: Optional[str] = None
    ) -> None:
        self.last_capture_path: str | None = None
        self.params = KWinDBusCaptureParams(
            width=width, height=height, monitor_id=monitor_id
        )

    def capture(self) -> np.ndarray:
        """Return an RGB frame as a numpy array or raise ``KWinDBusCaptureError``."""

        try:
            frame = self._try_capture_via_dbus()
        except Exception as exc:
            raise KWinDBusCaptureError(
                "KWin D-Bus screenshot failed. Ensure KDE Plasma session D-Bus is "
                "available and KWin screenshot interfaces are accessible."
            ) from exc

        if frame is None:
            raise KWinDBusCaptureError(
                "KWin D-Bus screenshot returned no frame. Verify KWin screenshot "
                "permissions/interface availability for this Plasma version."
            )

        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8, copy=False)

        if frame.ndim != 3 or frame.shape[2] != 3:
            raise KWinDBusCaptureError(
                f"KWin D-Bus screenshot returned invalid frame shape: {frame.shape}"
            )

        return frame

    def _run_async(self, coro):
        """Run async DBus calls in a dedicated loop for sync capture API."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _try_capture_via_dbus(self) -> Optional[np.ndarray]:
        reply = self._run_async(self._capture_reply_via_dbus())
        frame = self._decode_reply_to_rgb(reply)
        if frame is None:
            return None

        frame_h, frame_w = frame.shape[:2]
        target_h = int(self.params.height)
        target_w = int(self.params.width)
        if frame_h == target_h and frame_w == target_w:
            return frame

        return self._resize_frame(frame=frame, width=target_w, height=target_h)

    async def _capture_reply_via_dbus(self):
        from dbus_next.aio import MessageBus

        bus = await MessageBus().connect()
        last_exc: Exception | None = None

        for bus_name, path, interface_name in self._API_CANDIDATES:
            try:
                introspection = await bus.introspect(bus_name, path)
                proxy = bus.get_proxy_object(bus_name, path, introspection)
                iface = proxy.get_interface(interface_name)
            except Exception as exc:
                last_exc = exc
                continue

            for method_name in self._METHOD_CANDIDATES:
                call_method = getattr(iface, f"call_{method_name}", None)
                if call_method is None:
                    continue

                for args in self._candidate_args_for_method(method_name):
                    try:
                        reply = await call_method(*args)
                        self.last_capture_path = f"kwin-dbus:{method_name}"
                        return reply
                    except Exception as exc:
                        last_exc = exc
                        continue

        if last_exc is None:
            raise KWinDBusCaptureError(
                "No known KWin screenshot D-Bus API was available on this session bus."
            )

        raise KWinDBusCaptureError(
            "All known KWin screenshot D-Bus API variants failed."
        ) from last_exc

    def _candidate_args_for_method(self, method_name: str) -> tuple[tuple[object, ...], ...]:
        if method_name == "captureScreen" and self.params.monitor_id:
            return ((self.params.monitor_id,),)

        if method_name == "screenshotScreen":
            if self.params.monitor_id:
                return ((self.params.monitor_id,),)
            return ((0,),)

        # Most interfaces export a no-arg fullscreen screenshot method.
        return ((),)

    def _decode_reply_to_rgb(self, reply: object) -> Optional[np.ndarray]:
        payload = reply
        if isinstance(payload, tuple):
            payload = payload[0] if payload else None

        if payload is None:
            return None

        if isinstance(payload, str):
            path = Path(payload)
            if not path.exists():
                raise KWinDBusCaptureError(
                    f"KWin screenshot returned a non-existent file path: {path}"
                )

            ppm_rgb = self._decode_ppm_path(path)
            if ppm_rgb is not None:
                return ppm_rgb

            return self._decode_qimage_path(path)

        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        elif isinstance(payload, bytearray):
            payload = bytes(payload)
        elif isinstance(payload, list) and all(isinstance(v, int) for v in payload):
            payload = bytes(payload)

        if isinstance(payload, bytes):
            ppm_rgb = self._decode_ppm_bytes(payload)
            if ppm_rgb is not None:
                return ppm_rgb
            return self._decode_qimage_bytes(payload)

        raise KWinDBusCaptureError(
            f"Unsupported KWin screenshot payload type: {type(payload)!r}"
        )

    def _decode_ppm_path(self, path: Path) -> Optional[np.ndarray]:
        if path.suffix.lower() not in {".ppm", ".pnm"}:
            return None
        return self._decode_ppm_bytes(path.read_bytes())

    def _decode_ppm_bytes(self, data: bytes) -> Optional[np.ndarray]:
        if not data.startswith(b"P6"):
            return None

        # Minimal binary-PPM parser with comment support.
        idx = 2
        tokens: list[bytes] = []
        n = len(data)
        while len(tokens) < 3 and idx < n:
            while idx < n and data[idx] in b" \t\r\n":
                idx += 1
            if idx < n and data[idx:idx + 1] == b"#":
                while idx < n and data[idx] not in b"\r\n":
                    idx += 1
                continue
            start = idx
            while idx < n and data[idx] not in b" \t\r\n":
                idx += 1
            if start < idx:
                tokens.append(data[start:idx])

        if len(tokens) != 3:
            raise KWinDBusCaptureError("Invalid PPM screenshot payload header.")

        width = int(tokens[0])
        height = int(tokens[1])
        maxval = int(tokens[2])
        if maxval != 255:
            raise KWinDBusCaptureError("Unsupported PPM maxval (expected 255).")

        while idx < n and data[idx] in b" \t\r\n":
            idx += 1

        raw = data[idx:]
        expected = width * height * 3
        if len(raw) < expected:
            raise KWinDBusCaptureError("Incomplete PPM screenshot pixel payload.")

        arr = np.frombuffer(raw[:expected], dtype=np.uint8)
        return arr.reshape((height, width, 3)).copy()

    def _decode_qimage_path(self, path: Path) -> np.ndarray:
        try:
            from PyQt6.QtGui import QImage
        except Exception as exc:
            raise KWinDBusCaptureError(
                "PyQt6 QImage is unavailable for decoding non-PPM screenshot data."
            ) from exc

        image = QImage(str(path))
        if image.isNull():
            raise KWinDBusCaptureError(
                f"Failed to decode image from KWin screenshot path: {path}"
            )
        return self._qimage_to_rgb_array(image)

    def _decode_qimage_bytes(self, payload: bytes) -> np.ndarray:
        try:
            from PyQt6.QtGui import QImage
        except Exception as exc:
            raise KWinDBusCaptureError(
                "PyQt6 QImage is unavailable for decoding screenshot bytes."
            ) from exc

        image = QImage.fromData(payload)
        if image.isNull():
            raise KWinDBusCaptureError(
                "Failed to decode image bytes returned by KWin screenshot D-Bus call."
            )
        return self._qimage_to_rgb_array(image)

    def _qimage_to_rgb_array(self, image) -> np.ndarray:
        from PyQt6.QtGui import QImage

        rgb_image = image.convertToFormat(QImage.Format.Format_RGB888)
        width = rgb_image.width()
        height = rgb_image.height()

        ptr = rgb_image.bits()
        ptr.setsize(height * width * 3)
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 3))
        # Copy out so frame remains valid after QImage destruction.
        return arr.copy()

    def _resize_frame(self, *, frame: np.ndarray, width: int, height: int) -> np.ndarray:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage

        src_h, src_w, _ = frame.shape
        image = QImage(frame.data, src_w, src_h, src_w * 3, QImage.Format.Format_RGB888)
        resized = image.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return self._qimage_to_rgb_array(resized)
