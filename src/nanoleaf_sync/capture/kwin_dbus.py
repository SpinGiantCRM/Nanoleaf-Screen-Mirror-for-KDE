from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nanoleaf_sync.capture._utils import _resize_to_target
from nanoleaf_sync.color.capture_metadata import resolve_capture_metadata
from nanoleaf_sync.color.hdr import HDRMetadata, analyze_hdr_path, convert_frame_to_srgb8
from nanoleaf_sync.desktop_entry import (
    QT_DESKTOP_FILE_NAME,
    RESTRICTED_IFACE_MARKER,
    launch_context_snapshot,
    redact_launch_token,
)


@dataclass(frozen=True)
class KWinDBusCaptureParams:
    width: int
    height: int
    # If None, the implementation will use the primary screen.
    # Monitor selection is intentionally left flexible because KDE/KWin
    # export different identifiers depending on version/compositor.
    monitor_id: str | None = None


class KWinDBusCaptureError(RuntimeError):
    """Raised when KWin D-Bus screenshot capture is unavailable or fails."""


_MAX_CAPTURE_DIMENSION = 16384
_MAX_CAPTURE_BYTES = 64 * 1024 * 1024


def _validate_capture_dimensions(*, width: int, height: int, stride: int | None = None) -> None:
    for name, value in (("width", width), ("height", height)):
        if value <= 0 or value > _MAX_CAPTURE_DIMENSION:
            raise KWinDBusCaptureError(
                f"KWin screenshot {name} out of bounds: {value} (max {_MAX_CAPTURE_DIMENSION})."
            )
    if stride is not None and (stride <= 0 or stride > _MAX_CAPTURE_DIMENSION * 4):
        raise KWinDBusCaptureError(f"KWin screenshot stride out of bounds: {stride}.")


def _validate_capture_byte_size(size: int) -> None:
    if size <= 0 or size > _MAX_CAPTURE_BYTES:
        raise KWinDBusCaptureError(
            f"KWin screenshot payload size out of bounds: {size} bytes (max {_MAX_CAPTURE_BYTES})."
        )


def _allowed_screenshot_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed_roots: list[Path] = []
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        allowed_roots.append(Path(runtime_dir).resolve())
    allowed_roots.append(Path("/tmp").resolve())
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            if resolved.is_file():
                _validate_capture_byte_size(resolved.stat().st_size)
            return resolved
        except ValueError:
            continue
    raise KWinDBusCaptureError(f"KWin screenshot path is outside allowed directories: {path}")


@dataclass(frozen=True)
class _ScreenShot2Payload:
    data: bytes
    results: dict[str, Any]


def _parse_screenshot2_color_metadata(results: dict[str, Any]) -> dict[str, object] | None:
    transfer_raw = (
        results.get("transferFunction") or results.get("transfer") or results.get("colorTransfer")
    )
    primaries_raw = (
        results.get("colorSpace") or results.get("primaries") or results.get("colorPrimaries")
    )
    max_nits_raw = (
        results.get("maxLuminance")
        or results.get("max_nits")
        or results.get("masteringDisplayMaxLuminance")
    )
    if transfer_raw is None and primaries_raw is None and max_nits_raw is None:
        return None

    transfer_map = {
        "srgb": "srgb",
        "bt709": "srgb",
        "pq": "pq",
        "st2084": "pq",
        "perceptualquantizer": "pq",
        "hlg": "hlg",
        "linear": "linear",
    }
    primaries_map = {
        "srgb": "bt709",
        "bt709": "bt709",
        "rec709": "bt709",
        "bt2020": "bt2020",
        "rec2020": "bt2020",
        "bt.2020": "bt2020",
    }

    metadata: dict[str, object] = {"source": "kwin screenshot2 metadata"}
    if transfer_raw is not None:
        normalized_transfer = str(transfer_raw).strip().lower().replace(" ", "")
        metadata["transfer"] = transfer_map.get(normalized_transfer, str(transfer_raw))
    if primaries_raw is not None:
        normalized_primaries = str(primaries_raw).strip().lower().replace(" ", "")
        metadata["primaries"] = primaries_map.get(normalized_primaries, str(primaries_raw))
    if max_nits_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            metadata["max_nits"] = float(max_nits_raw)
    return metadata


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
    _RECONNECT_RETRY_DELAY_SECONDS = 0.05
    _LOOP_WAKE_INTERVAL_SECONDS = 0.05

    def __init__(
        self,
        width: int,
        height: int,
        monitor_id: str | None = None,
        *,
        hdr_max_nits: float = 1000.0,
        hdr_transfer: str = "srgb",
        hdr_primaries: str = "bt709",
    ) -> None:
        self.last_capture_path: str | None = None
        self.last_hdr_diagnostics: dict[str, object] = {}
        self._last_screenshot2_color_metadata: dict[str, object] | None = None
        self.params = KWinDBusCaptureParams(width=width, height=height, monitor_id=monitor_id)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._loop_lock = threading.Lock()
        self._screenshot2_bus = None
        self._screenshot2_introspection = None
        self._legacy_bus = None
        self._loop_start_error: BaseException | None = None
        self._hdr_defaults = HDRMetadata(
            transfer=hdr_transfer
            if hdr_transfer in ("srgb", "pq", "hlg", "linear", "unknown")
            else "srgb",  # type: ignore[arg-type]
            primaries=hdr_primaries if hdr_primaries in ("bt709", "bt2020", "unknown") else "bt709",  # type: ignore[arg-type]
            max_nits=float(hdr_max_nits),
        )
        self._resize_index_cache: dict[
            tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]
        ] = {}
        self._resize_index_cache_limit = 8
        self._legacy_introspection_cache: dict[tuple[str, str], object] = {}
        self._legacy_introspection_cache_max = 4

    def capture(self) -> np.ndarray:
        """Return an RGB frame as a numpy array or raise ``KWinDBusCaptureError``."""
        self._last_screenshot2_color_metadata = None

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

        frame = self._convert_if_needed(frame)

        if frame.ndim != 3 or frame.shape[2] != 3:
            raise KWinDBusCaptureError(
                f"KWin D-Bus screenshot returned invalid frame shape: {frame.shape}"
            )

        return frame

    def _convert_if_needed(self, frame: np.ndarray) -> np.ndarray:
        backend_meta = self._last_screenshot2_color_metadata
        user_meta = resolve_capture_metadata(
            backend_metadata=backend_meta,
            user_transfer=self._hdr_defaults.transfer,
            user_primaries=self._hdr_defaults.primaries,
            user_max_nits=float(self._hdr_defaults.max_nits),
            display_preset="hdr",
            kwin_display_referred=backend_meta is None,
        )
        meta = user_meta.to_hdr_metadata()
        self.last_hdr_diagnostics = {
            **analyze_hdr_path(
                frame,
                metadata={
                    "transfer": meta.transfer,
                    "primaries": meta.primaries,
                    "max_nits": meta.max_nits,
                    "source": user_meta.source,
                },
            ),
            "hdr_max_nits": float(meta.max_nits),
            "assumption": user_meta.assumption,
            "skip_display_gamut_adaptation": user_meta.skip_display_gamut_adaptation,
        }
        if frame.dtype == np.uint8 and meta.transfer == "srgb" and meta.primaries == "bt709":
            return frame
        return convert_frame_to_srgb8(
            frame,
            metadata={
                "transfer": meta.transfer,
                "primaries": meta.primaries,
                "max_nits": meta.max_nits,
                "source": user_meta.source,
            },
        )

    def _run_async(self, coro, *, timeout: float = 2.0):
        """Run async DBus calls in a dedicated loop for sync capture API.

        A *timeout* (default 2.0 s) prevents the capture worker from blocking
        indefinitely when a D-Bus call hangs.  The caller (typically the capture
        worker) catches the resulting :exc:`TimeoutError` / :exc:`KWinDBusCaptureError`
        and retries or exits in response to the runtime stop event.
        """
        loop = self._ensure_background_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=max(0.1, float(timeout)))
        except TimeoutError:
            # The future may still be pending; cancel it on the event-loop
            # thread so we don't leak tasks.
            future.cancel()
            raise KWinDBusCaptureError(
                f"KWin D-Bus call timed out after {timeout:.1f}s. "
                "The compositor may be busy or the D-Bus session is unresponsive."
            ) from None

    def _ensure_background_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is not None and loop.is_running():
            return loop

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

            def _keep_loop_waking() -> None:
                if loop.is_running():
                    loop.call_later(self._LOOP_WAKE_INTERVAL_SECONDS, _keep_loop_waking)

            if hasattr(loop, "call_soon"):
                loop.call_soon(self._loop_ready.set)
                loop.call_soon(_keep_loop_waking)
            else:
                self._loop_ready.set()
            loop.run_forever()
            loop.close()
        except asyncio.CancelledError:
            try:
                loop.close()
            except Exception:
                logger.debug("Failed to close asyncio loop on cancellation", exc_info=True)
            self._loop = None
            self._loop_ready.set()
        except Exception as exc:
            self._loop_start_error = exc
            self._loop = None
            self._loop_ready.set()

    def close(self) -> None:
        with self._loop_lock:
            self._resize_index_cache.clear()
            self._legacy_introspection_cache.clear()
            loop = self._loop
            if loop is None:
                self._screenshot2_bus = None
                self._legacy_bus = None
                return
            if loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(self._reset_bus_connections(), loop)
                    future.result(timeout=2.0)
                except (TimeoutError, Exception):
                    logger = __import__("logging").getLogger(__name__)
                    logger.warning(
                        "KWin D-Bus bus reset timed out or failed during close",
                        exc_info=True,
                    )
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except Exception:
                    logger.debug("Failed to stop asyncio loop during close", exc_info=True)
            else:
                self._screenshot2_bus = None
                self._legacy_bus = None
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=3.0)
                if self._loop_thread.is_alive():
                    import logging

                    logging.getLogger(__name__).warning(
                        "KWin D-Bus event loop thread did not exit within 3s timeout"
                    )

            if loop is not None:
                assert loop.is_closed() or not loop.is_running()
            self._loop = None
            self._loop_thread = None
            self._loop_ready.clear()
            self._screenshot2_bus = None
            self._legacy_bus = None

    def _try_capture_via_dbus(self) -> np.ndarray | None:
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
        screenshot2_exc: Exception | None = None
        try:
            return await self._call_with_reconnect(self._capture_reply_via_screenshot2)
        except Exception as exc:
            screenshot2_exc = exc
            if self._is_authorization_error(exc):
                raise KWinDBusCaptureError(
                    "KWin authorization denied for ScreenShot2. "
                    f"Details: {self._format_exception_details(exc)}"
                ) from exc

        legacy_exc: Exception | None = None
        try:
            return await self._call_with_reconnect(self._capture_reply_via_legacy_interfaces)
        except Exception as exc:
            legacy_exc = exc

        raise KWinDBusCaptureError(
            "No usable KWin screenshot API on this Plasma session. "
            f"ScreenShot2: {self._format_exception_details(screenshot2_exc)}. "
            f"Legacy: {self._format_exception_details(legacy_exc)}."
        ) from (legacy_exc or screenshot2_exc)

    async def _call_with_reconnect(self, func):
        try:
            return await func()
        except Exception as exc:
            if not self._is_reconnectable_bus_error(exc):
                raise
            await self._reset_bus_connections()
            await asyncio.sleep(self._RECONNECT_RETRY_DELAY_SECONDS)
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
        self._screenshot2_introspection = None
        self._legacy_bus = None
        self._legacy_introspection_cache.clear()

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

    async def _get_screenshot2_introspection(self):
        bus_name, path, _ = self._SCREENSHOT2_API
        bus = await self._get_screenshot2_bus()
        if self._screenshot2_introspection is None:
            self._screenshot2_introspection = await bus.introspect(bus_name, path)
        return self._screenshot2_introspection

    async def _get_legacy_bus(self):
        if self._legacy_bus is None:
            self._legacy_bus = await self._connect_legacy_bus()
        return self._legacy_bus

    async def _capture_reply_via_screenshot2(self):
        from dbus_next import Message, MessageType

        bus_name, path, interface_name = self._SCREENSHOT2_API
        bus = await self._get_screenshot2_bus()
        await self._get_screenshot2_introspection()

        attempt_errors: list[tuple[str, str, Exception]] = []
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
                os.close(write_fd)
                write_fd = -1

                results = reply.body[0] if reply.body else {}
                result_map = self._normalize_variant_dict(results)
                stride = int(result_map.get("stride", 0) or 0)
                height = int(result_map.get("height", 0) or 0)
                expected_bytes = stride * height
                frame_data = self._read_fd_exact(
                    read_fd,
                    expected_bytes,
                    stride=stride,
                    height=height,
                )
                self.last_capture_path = f"kwin-dbus:{method_name}"
                return _ScreenShot2Payload(data=frame_data, results=results)
            except Exception as exc:
                attempt_errors.append((method_name, signature, exc))
            finally:
                os.close(read_fd)
                if write_fd >= 0:
                    os.close(write_fd)

        if not attempt_errors:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 interface was available but no capture methods were callable."
            )
        if any(self._is_authorization_error(exc) for _, _, exc in attempt_errors):
            auth_exc = next(
                exc for _, _, exc in attempt_errors if self._is_authorization_error(exc)
            )
            raise auth_exc

        if all(self._is_signature_or_method_error(exc) for _, _, exc in attempt_errors):
            attempted = ", ".join(f"{name}({sig})" for name, sig, _ in attempt_errors)
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 interface is present but method/signature is incompatible "
                f"with this Plasma version. Attempted: {attempted}."
            ) from attempt_errors[-1][2]

        raise KWinDBusCaptureError(
            "KWin ScreenShot2 capture failed. "
            f"Last error: {self._format_exception_details(attempt_errors[-1][2])}"
        ) from attempt_errors[-1][2]

    async def _capture_reply_via_legacy_interfaces(self):
        bus = await self._get_legacy_bus()
        last_exc: Exception | None = None

        for bus_name, path, interface_name in self._LEGACY_API_CANDIDATES:
            try:
                cache_key = (bus_name, path)
                introspection = self._legacy_introspection_cache.get(cache_key)
                if introspection is None:
                    introspection = await bus.introspect(bus_name, path)
                    self._legacy_introspection_cache[cache_key] = introspection
                    if len(self._legacy_introspection_cache) > self._legacy_introspection_cache_max:
                        self._legacy_introspection_cache.pop(
                            next(iter(self._legacy_introspection_cache))
                        )
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
            attempts.append(("CaptureScreen", "sa{sv}h", [self.params.monitor_id, options]))
        else:
            attempts.append(("CaptureScreen", "sa{sv}h", ["", options]))
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
            context = launch_context_snapshot()
            startup_id = redact_launch_token(context.get("DESKTOP_STARTUP_ID"))
            activation = redact_launch_token(context.get("XDG_ACTIVATION_TOKEN"))
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 access denied by KDE policy. This can happen when KDE cannot "
                "associate this process with an authorized desktop entry. Confirm the running app "
                f"uses Qt desktop file name '{QT_DESKTOP_FILE_NAME}' and the launcher desktop file "
                f"contains '{RESTRICTED_IFACE_MARKER}'. Launch context: "
                f"DESKTOP_STARTUP_ID={startup_id}; "
                f"XDG_ACTIVATION_TOKEN={activation}. "
                "If launcher metadata changed, restart the Plasma session."
            )

        raise KWinDBusCaptureError(f"KWin ScreenShot2 call failed: {error_name} {details}".strip())

    def _is_authorization_error(self, exc: Exception) -> bool:
        message = self._format_exception_details(exc).lower()
        return any(
            token in message
            for token in ("accessdenied", "notauthorized", "noauthorized", "access denied")
        )

    def _is_signature_or_method_error(self, exc: Exception) -> bool:
        message = self._format_exception_details(exc).lower()
        return any(
            token in message
            for token in (
                "unknownmethod",
                "invalidargs",
                "invalid signature",
                "signature",
                "method",
            )
        )

    def _format_exception_details(self, exc: Exception | None) -> str:
        if exc is None:
            return "not attempted"
        error_type = str(getattr(exc, "type", "")).strip()
        message = str(exc).strip()
        if error_type and message:
            return f"{error_type}: {message}"
        if error_type:
            return error_type
        return message or exc.__class__.__name__

    def _read_all_bytes_from_fd(self, fd: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _read_fd_exact(
        self,
        fd: int,
        expected_size: int | None,
        *,
        stride: int | None = None,
        height: int | None = None,
    ) -> bytes:
        if expected_size is None:
            return self._read_all_bytes_from_fd(fd)
        if expected_size == 0:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 reported zero expected bytes "
                f"(stride={stride!r}, height={height!r}, expected_bytes={expected_size})."
            )
        if expected_size < 0:
            raise KWinDBusCaptureError(
                "KWin ScreenShot2 reported a negative expected byte count "
                f"(stride={stride!r}, height={height!r}, expected_bytes={expected_size})."
            )

        buffer = bytearray(expected_size)
        view = memoryview(buffer)
        read_total = 0
        while read_total < expected_size:
            chunk = os.read(fd, expected_size - read_total)
            if not chunk:
                raise KWinDBusCaptureError(
                    "KWin ScreenShot2 pipe closed before delivering the full frame payload "
                    f"(expected={expected_size} bytes, received={read_total} bytes, "
                    f"stride={stride!r}, height={height!r})."
                )
            chunk_len = len(chunk)
            view[read_total : read_total + chunk_len] = chunk
            read_total += chunk_len
        return bytes(view[:read_total])

    def _candidate_args_for_method(self, method_name: str) -> tuple[tuple[object, ...], ...]:
        if method_name == "captureScreen" and self.params.monitor_id:
            return ((self.params.monitor_id,),)

        if method_name == "screenshotScreen":
            if self.params.monitor_id:
                return ((self.params.monitor_id,),)
            return ((0,),)

        # Most interfaces export a no-arg fullscreen screenshot method.
        return ((),)

    def _decode_reply_to_rgb(self, reply: object) -> np.ndarray | None:
        if isinstance(reply, _ScreenShot2Payload):
            return self._decode_screenshot2_payload(reply)

        payload = reply
        if isinstance(payload, tuple):
            payload = payload[0] if payload else None

        if payload is None:
            return None

        if isinstance(payload, str):
            path = _allowed_screenshot_path(Path(payload))
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
        elif isinstance(payload, bytearray) or (
            isinstance(payload, list) and all(isinstance(v, int) for v in payload)
        ):
            payload = bytes(payload)

        if isinstance(payload, bytes):
            ppm_rgb = self._decode_ppm_bytes(payload)
            if ppm_rgb is not None:
                return ppm_rgb
            try:
                return self._decode_qimage_bytes(payload)
            except KWinDBusCaptureError as exc:
                raise KWinDBusCaptureError(
                    "KWin screenshot payload decode failed for byte payload."
                ) from exc

        raise KWinDBusCaptureError(f"Unsupported KWin screenshot payload type: {type(payload)!r}")

    def _decode_screenshot2_payload(self, reply: _ScreenShot2Payload) -> np.ndarray:
        results = self._normalize_variant_dict(reply.results)
        self._last_screenshot2_color_metadata = _parse_screenshot2_color_metadata(results)
        image_type = results.get("type")
        if image_type != "raw":
            raise KWinDBusCaptureError(f"Unsupported KWin ScreenShot2 result type: {image_type!r}")
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

        _validate_capture_dimensions(width=width, height=height, stride=stride)
        expected_bytes = stride * height
        _validate_capture_byte_size(expected_bytes)
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

    def _decode_ppm_path(self, path: Path) -> np.ndarray | None:
        if path.suffix.lower() not in {".ppm", ".pnm"}:
            return None
        _validate_capture_byte_size(path.stat().st_size)
        return self._decode_ppm_bytes(path.read_bytes())

    def _decode_ppm_bytes(self, data: bytes) -> np.ndarray | None:
        if not data.startswith(b"P6"):
            return None

        # Minimal binary-PPM parser with comment support.
        idx = 2
        tokens: list[bytes] = []
        n = len(data)
        while len(tokens) < 3 and idx < n:
            while idx < n and data[idx] in b" \t\r\n":
                idx += 1
            if idx < n and data[idx : idx + 1] == b"#":
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
        _validate_capture_dimensions(width=width, height=height)
        if maxval != 255:
            raise KWinDBusCaptureError("Unsupported PPM maxval (expected 255).")

        while idx < n and data[idx] in b" \t\r\n":
            idx += 1

        raw = data[idx:]
        expected = width * height * 3
        _validate_capture_byte_size(expected)
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
            raise KWinDBusCaptureError(f"Failed to decode image from KWin screenshot path: {path}")
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
        known_rgb = self._decode_known_qimage_raw_formats(
            data=data,
            width=width,
            height=height,
            stride=stride,
            image_format=image_format,
        )
        if known_rgb is not None:
            return known_rgb

        try:
            from PyQt6.QtGui import QImage
        except Exception as exc:
            raise KWinDBusCaptureError(
                "PyQt6 QImage is required to decode KWin ScreenShot2 raw frames."
            ) from exc

        fmt = QImage.Format(image_format)
        # Copy into a mutable buffer so QImage can safely reference it until conversion.
        raw_copy = bytearray(data)
        image = QImage(raw_copy, width, height, stride, fmt)
        if image.isNull():
            raise KWinDBusCaptureError(
                f"KWin ScreenShot2 returned unsupported QImage format id: {image_format}"
            )
        return self._qimage_to_rgb_array(image)

    def _decode_known_qimage_raw_formats(
        self, *, data: bytes, width: int, height: int, stride: int, image_format: int
    ) -> np.ndarray | None:
        if sys.byteorder != "little":
            return None
        # Qt: RGB32=4, ARGB32=5. Both are B G R A/x in memory order on little-endian.
        if image_format not in (4, 5):
            return None
        if stride < width * 4 or len(data) < stride * height:
            return None

        arr = np.frombuffer(data, dtype=np.uint8).reshape(height, stride)
        pixels = arr[:, : width * 4].reshape(height, width, 4)
        # BGRx/BGRA -> RGB
        return pixels[:, :, :3][:, :, ::-1].copy()

    def _resize_frame(self, *, frame: np.ndarray, width: int, height: int) -> np.ndarray:
        return _resize_to_target(
            frame=frame,
            target_height=height,
            target_width=width,
            index_cache=self._resize_index_cache,
            index_cache_limit=self._resize_index_cache_limit,
        )
