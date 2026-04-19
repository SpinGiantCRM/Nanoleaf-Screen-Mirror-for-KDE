from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

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


@dataclass(frozen=True)
class _ScreenShot2Payload:
    data: bytes
    results: dict[str, Any]


class KWinDBusScreenshotCapture:
    """KWin D-Bus screenshot capture backend."""

    name = "kwin-dbus"

    _SCREENSHOT2_API = (
        "org.kde.KWin",
        "/org/kde/KWin/ScreenShot2",
        "org.kde.KWin.ScreenShot2",
    )

    _LEGACY_API_CANDIDATES = (
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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._loop_lock = threading.Lock()
        self._screenshot2_bus = None
        self._legacy_bus = None
        self._loop_start_error: BaseException | None = None

    def capture(self) -> np.ndarray:
        """Return an RGB frame as a numpy array or raise ``KWinDBusCaptureError``."""

        try:
            frame = self._try_capture_via_dbus()
        except KWinDBusCaptureError:
            raise
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
        loop = self._ensure_background_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def _ensure_background_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            self._loop_ready.clear()
            self._loop_thread = threading.Thread(
                target=self._loop_worker,
                name="kwin-dbus-capture",
                daemon=True,
            )
            self._loop_thread.start()

        self._loop_ready.wait(timeout=2.0)

        with self._loop_lock:
            if self._loop is None or not self._loop.is_running():
                if self._loop_start_error is not None:
                    raise KWinDBusCaptureError(
                        "Failed to initialize KWin D-Bus event loop."
                    ) from self._loop_start_error
                raise KWinDBusCaptureError("Failed to initialize KWin D-Bus event loop.")
            return self._loop

    def _loop_worker(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            self._loop_start_error = None
            asyncio.set_event_loop(loop)
            self._loop_ready.set()
            loop.run_forever()
            loop.close()
        except BaseException as exc:
            self._loop_start_error = exc
            self._loop = None
            self._loop_ready.set()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            self._screenshot2_bus = None
            self._legacy_bus = None
            return
        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._reset_bus_connections(), loop
                )
                future.result(timeout=1.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        else:
            self._screenshot2_bus = None
            self._legacy_bus = None
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=1.0)

        self._loop = None
        self._loop_thread = None
        self._loop_ready.clear()
        self._screenshot2_bus = None
        self._legacy_bus = None

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
        # Fallback order is explicit: modern ScreenShot2 first, legacy KWin
        # screenshot methods second.
        last_exc: Exception | None = None
        try:
            return await self._call_with_reconnect(self._capture_reply_via_screenshot2)
        except Exception as exc:
            last_exc = exc

        try:
            return await self._call_with_reconnect(
                self._capture_reply_via_legacy_interfaces
            )
        except Exception as exc:
            if last_exc is None:
                last_exc = exc

        raise KWinDBusCaptureError(
            "All known KWin screenshot D-Bus API variants failed."
        ) from last_exc

    async def _call_with_reconnect(self, func):
        try:
            return await func()
        except Exception as exc:
            if not self._is_reconnectable_bus_error(exc):
                raise
            await self._reset_bus_connections()
            return await func()

    def _is_reconnectable_bus_error(self, exc: Exception) -> bool:
        error_name = str(getattr(exc, "type", ""))
        message = str(exc)
        reconnectable_markers = (
            "org.freedesktop.DBus.Error.Disconnected",
            "org.freedesktop.DBus.Error.NoReply",
            "org.freedesktop.DBus.Error.NameHasNoOwner",
            "org.freedesktop.DBus.Error.ServiceUnknown",
            "Disconnected",
            "connection reset",
            "broken pipe",
            "closed",
        )
        combined = f"{error_name} {message}".lower()
        return any(marker.lower() in combined for marker in reconnectable_markers)

    async def _disconnect_bus(self, bus: Any) -> None:
        if bus is None:
            return
        disconnect = getattr(bus, "disconnect", None)
        if disconnect is None:
            return
        result = disconnect()
        if asyncio.iscoroutine(result):
            await result

    async def _reset_bus_connections(self) -> None:
        await self._disconnect_bus(self._screenshot2_bus)
        await self._disconnect_bus(self._legacy_bus)
        self._screenshot2_bus = None
        self._legacy_bus = None

    async def _connect_screenshot2_bus(self):
        from dbus_next.aio import MessageBus

        return await MessageBus(negotiate_unix_fd=True).connect()

    async def _connect_legacy_bus(self):
        from dbus_next.aio import MessageBus

        return await MessageBus().connect()

    async def _get_screenshot2_bus(self):
        if self._screenshot2_bus is None:
            self._screenshot2_bus = await self._connect_screenshot2_bus()
        return self._screenshot2_bus

    async def _get_legacy_bus(self):
        if self._legacy_bus is None:
            self._legacy_bus = await self._connect_legacy_bus()
        return self._legacy_bus

    async def _capture_reply_via_screenshot2(self):
        from dbus_next import Message, MessageType

        bus_name, path, interface_name = self._SCREENSHOT2_API
        bus = await self._get_screenshot2_bus()
        await bus.introspect(bus_name, path)

        last_exc: Exception | None = None
        for method_name, signature, base_args in self._screenshot2_method_attempts():
            read_fd, write_fd = os.pipe()
            try:
                msg = Message(
                    destination=bus_name,
                    path=path,
                    interface=interface_name,
                    member=method_name,
                    signature=signature,
                    # DBus type `h` carries an index into the unix_fds array.
                    body=[*base_args, 0],
                    unix_fds=[write_fd],
                )
                reply = await bus.call(msg)
                if reply.message_type == MessageType.ERROR:
                    self._raise_screenshot2_error(reply)

                results = reply.body[0] if reply.body else {}
                frame_data = self._read_all_bytes_from_fd(read_fd)
                self.last_capture_path = f"kwin-dbus:{method_name}"
                return _ScreenShot2Payload(data=frame_data, results=results)
            except Exception as exc:
                last_exc = exc
            finally:
                os.close(read_fd)
                os.close(write_fd)

        if last_exc is None:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 interface was available but no capture methods were callable."
            )
        raise last_exc

    async def _capture_reply_via_legacy_interfaces(self):
        bus = await self._get_legacy_bus()
        last_exc: Exception | None = None

        for bus_name, path, interface_name in self._LEGACY_API_CANDIDATES:
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
        raise last_exc

    def _screenshot2_method_attempts(
        self,
    ) -> tuple[tuple[str, str, list[Any]], ...]:
        options: dict[str, Any] = {}
        attempts: list[tuple[str, str, list[Any]]] = []

        if self.params.monitor_id:
            attempts.append(
                ("CaptureScreen", "sa{sv}h", [self.params.monitor_id, options])
            )

        # If monitor name is unknown, some KWin versions map an empty name to
        # the primary output.
        attempts.append(("CaptureScreen", "sa{sv}h", ["", options]))

        # Conservative fallback: explicit area at configured dimensions.
        attempts.append(
            (
                "CaptureArea",
                "iiuua{sv}h",
                [0, 0, int(self.params.width), int(self.params.height), options],
            )
        )
        return tuple(attempts)

    def _raise_screenshot2_error(self, reply: Any) -> None:
        error_name = getattr(reply, "error_name", "org.freedesktop.DBus.Error.Failed")
        details = ""
        if getattr(reply, "body", None):
            details = str(reply.body[0])

        if (
            "AccessDenied" in error_name
            or "NotAuthorized" in error_name
            or "NotAuthorized" in details
            or "NoAuthorized" in error_name
            or "NoAuthorized" in details
        ):
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 access denied by KDE policy. If you launched from a plain "
                "terminal, run via the installed desktop entry/launcher so KDE grants "
                "screenshot permissions. For packaged/manual launchers, ensure the desktop file "
                "includes X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 and then "
                "restart the KDE session."
            )

        raise KWinDBusCaptureError(
            f"KWin ScreenShot2 call failed: {error_name} {details}".strip()
        )

    def _read_all_bytes_from_fd(self, fd: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

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
        if isinstance(reply, _ScreenShot2Payload):
            return self._decode_screenshot2_payload(reply)

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

    def _decode_screenshot2_payload(self, reply: _ScreenShot2Payload) -> np.ndarray:
        results = self._normalize_variant_dict(reply.results)
        image_type = results.get("type")
        if image_type != "raw":
            raise KWinDBusCaptureError(
                f"Unsupported KWin ScreenShot2 result type: {image_type!r}"
            )
        try:
            width = int(results["width"])
            height = int(results["height"])
            stride = int(results["stride"])
            image_format = int(results["format"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 reply missing required raw metadata "
                "(type/width/height/stride/format)."
            ) from exc

        expected_bytes = stride * height
        if len(reply.data) < expected_bytes:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 raw payload shorter than expected from stride/height."
            )

        return self._decode_qimage_raw_frame(
            data=reply.data[:expected_bytes],
            width=width,
            height=height,
            stride=stride,
            image_format=image_format,
        )

    def _normalize_variant_dict(self, values: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            normalized[key] = getattr(value, "value", value)
        return normalized

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

    def _decode_qimage_raw_frame(
        self, *, data: bytes, width: int, height: int, stride: int, image_format: int
    ) -> np.ndarray:
        try:
            from PyQt6.QtGui import QImage
        except Exception as exc:
            raise KWinDBusCaptureError(
                "PyQt6 QImage is required to decode KWin ScreenShot2 raw frames."
            ) from exc

        fmt = QImage.Format(image_format)
        raw_copy = bytearray(data)
        image = QImage(raw_copy, width, height, stride, fmt)
        if image.isNull():
            raise KWinDBusCaptureError(
                f"KWin ScreenShot2 returned unsupported QImage format id: {image_format}"
            )
        return self._qimage_to_rgb_array(image)

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
