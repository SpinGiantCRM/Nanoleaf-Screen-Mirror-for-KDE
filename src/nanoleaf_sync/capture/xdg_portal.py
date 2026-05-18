"""XDG ScreenCast portal capture backend.

Uses org.freedesktop.portal.ScreenCast for compositor-agnostic Wayland capture.
The backend negotiates a portal session over D-Bus and then consumes frames via
PipeWire. A restore token is persisted so users are not repeatedly prompted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
import threading
import time

from nanoleaf_sync.capture.portal_helpers import random_token, request_path, unwrap_variant
from pathlib import Path
from typing import Optional

import numpy as np


logger = logging.getLogger(__name__)


class XDGPortalError(RuntimeError):
    """Raised when portal negotiation or PipeWire capture fails."""


@dataclass(slots=True)
class PortalDiagnosticState:
    stages: list[dict[str, object]]
    last_success_stage: str
    failing_stage: str
    negotiated_caps: str | None = None
    empty_buffer_count: int = 0
    expected_bytes: int = 0
    received_bytes: int = 0
    timeout_s: float = 0.0
    sample_received: bool = False
    buffer_present: bool = False
    buffer_reported_size: int = 0
    memory_count: int = 0
    mapped_memory_size: int = 0
    stride: int | None = None
    pts_ns: int | None = None
    dts_ns: int | None = None
    duration_ns: int | None = None
    negotiated_format: str | None = None
    negotiated_width: int | None = None
    negotiated_height: int | None = None
    negotiated_framerate: str | None = None
    non_empty_buffer_count: int = 0

    def mark(self, stage: str, status: str, detail: str = "") -> None:
        self.stages.append({"stage": stage, "status": status, "detail": detail})
        if status == "ok":
            self.last_success_stage = stage
        elif status == "failed":
            self.failing_stage = stage


class XDGPortalCapture:
    """Screen capture via org.freedesktop.portal.ScreenCast + PipeWire."""

    name = "xdg-portal"

    _PORTAL_BUS = "org.freedesktop.portal.Desktop"
    _PORTAL_PATH = "/org/freedesktop/portal/desktop"
    _PORTAL_IFACE = "org.freedesktop.portal.ScreenCast"
    _SESSION_IFACE = "org.freedesktop.portal.Session"
    _REQUEST_IFACE = "org.freedesktop.portal.Request"
    _GSTREAMER_FIRST_FRAME_TIMEOUT_S = 6.0
    _GSTREAMER_FIRST_FRAME_POLL_INTERVAL_S = 0.02
    _MAX_EMPTY_FIRST_BUFFERS = 12
    _APP_SINK_FORMATS = ("RGB", "BGR", "BGRx", "RGBx", "RGBA", "BGRA")

    def __init__(
        self,
        width: int,
        height: int,
        *,
        restore_token_path: Optional[Path] = None,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.last_capture_path: str | None = None

        self._token_path = restore_token_path or (
            Path.home() / ".config" / "nanoleaf-kde-sync" / "portal_token"
        )
        self._pw_fd: Optional[int] = None
        self._node_id: Optional[int] = None
        self._session_handle: Optional[str] = None
        self._portal_bus = None
        self._initialized = False
        self._use_gstreamer = False
        self._empty_first_buffers = 0
        self._non_empty_first_buffers = 0
        self._last_frame_diag: dict[str, object] = {}
        self._caps_video_info_cache: dict[str, int] = {}
        self._caps_video_info_cache_max = 8

    def initialize(self) -> None:
        """Negotiate portal session and open PipeWire stream."""
        if self._initialized:
            return
        self._pw_fd, self._node_id = self._negotiate_portal_sync()
        self._open_pipewire_stream(self._pw_fd, self._node_id)
        self._initialized = True
        self.last_capture_path = "xdg-portal:pipewire"

    def capture(self) -> np.ndarray:
        if not self._initialized:
            self.initialize()
        frame = self._read_pipewire_frame()
        if frame is None:
            raise XDGPortalError("PipeWire stream returned no frame.")
        return frame

    def close(self) -> None:
        self._close_pipewire_stream()
        if self._pw_fd is not None:
            try:
                os.close(self._pw_fd)
            except OSError:
                pass
            self._pw_fd = None
        self._close_portal_session_sync()
        self._initialized = False

    def _negotiate_portal_sync(self) -> tuple[int, int]:
        result: list[tuple[int, int]] = []
        error: list[BaseException] = []

        def _worker() -> None:
            loop: asyncio.AbstractEventLoop | None = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                fd, node = loop.run_until_complete(self._negotiate_portal())
                result.append((fd, node))
            except BaseException as exc:  # pragma: no cover - thread handoff
                error.append(exc)
            finally:
                if loop is not None:
                    loop.close()

        worker = threading.Thread(target=_worker, name="portal-negotiate", daemon=True)
        worker.start()
        worker.join()

        if error:
            raise XDGPortalError(f"Portal negotiation failed: {error[0]}") from error[0]
        if not result:
            raise XDGPortalError("Portal negotiation failed: no result returned.")
        return result[0]

    async def _negotiate_portal(self) -> tuple[int, int]:
        from dbus_next import Message, MessageType, Variant
        from dbus_next.aio import MessageBus

        bus = await MessageBus(negotiate_unix_fd=True).connect()
        self._portal_bus = bus
        unique_name = getattr(bus, "unique_name", None)
        if not unique_name:
            raise XDGPortalError("Portal negotiation failed: D-Bus unique name is unavailable.")
        sender = str(unique_name).replace(".", "_").lstrip(":")

        async def _call(method: str, signature: str, body: list, *, handle_token: str):
            portal_request_path = request_path(sender_name=sender, handle_token=handle_token)
            future: asyncio.Future = asyncio.get_event_loop().create_future()

            def _on_signal(msg):
                if msg is None:
                    return
                if (
                    msg.path == portal_request_path
                    and msg.interface == self._REQUEST_IFACE
                    and msg.member == "Response"
                    and not future.done()
                ):
                    future.set_result(msg)

            bus.add_message_handler(_on_signal)
            try:
                reply = await bus.call(
                    Message(
                        destination=self._PORTAL_BUS,
                        path=self._PORTAL_PATH,
                        interface=self._PORTAL_IFACE,
                        member=method,
                        signature=signature,
                        body=body,
                    )
                )
                if reply is None:
                    raise XDGPortalError(f"Portal {method} call failed: empty D-Bus reply.")
                if reply.message_type == MessageType.ERROR:
                    raise XDGPortalError(f"Portal {method} call failed: {reply.error_name}")
                return await asyncio.wait_for(future, timeout=120.0)
            finally:
                bus.remove_message_handler(_on_signal)

        session_token = random_token("nanoleaf_")
        handle_token = random_token("h")
        create_options: dict[str, Variant] = {
            "handle_token": Variant("s", handle_token),
            "session_handle_token": Variant("s", session_token),
        }
        msg = await _call("CreateSession", "a{sv}", [create_options], handle_token=handle_token)
        response_code = msg.body[0]
        if response_code != 0:
            raise XDGPortalError(f"CreateSession denied (response={response_code}).")
        session_handle = msg.body[1]["session_handle"].value
        self._session_handle = str(session_handle)

        restore_token = self._load_restore_token()
        handle_token2 = random_token("h")
        src_options: dict[str, Variant] = {
            "handle_token": Variant("s", handle_token2),
            "types": Variant("u", 1),
            "multiple": Variant("b", False),
            "cursor_mode": Variant("u", 2),
            "persist_mode": Variant("u", 2),
        }
        if restore_token:
            src_options["restore_token"] = Variant("s", restore_token)

        msg2 = await _call(
            "SelectSources",
            "oa{sv}",
            [session_handle, src_options],
            handle_token=handle_token2,
        )
        if msg2.body[0] != 0:
            raise XDGPortalError(f"SelectSources denied (response={msg2.body[0]}).")

        handle_token3 = random_token("h")
        start_options: dict[str, Variant] = {
            "handle_token": Variant("s", handle_token3),
        }
        msg3 = await _call(
            "Start",
            "osa{sv}",
            [session_handle, "", start_options],
            handle_token=handle_token3,
        )
        if msg3.body[0] != 0:
            raise XDGPortalError(f"Start denied (response={msg3.body[0]}).")

        results = msg3.body[1]
        streams = results.get("streams")
        if not streams:
            raise XDGPortalError("Portal Start returned no streams.")

        new_restore = results.get("restore_token")
        if new_restore:
            self._save_restore_token(str(unwrap_variant(new_restore)))

        first_stream = unwrap_variant(streams)[0]
        node_id = int(first_stream[0])

        pw_reply = await bus.call(
            Message(
                destination=self._PORTAL_BUS,
                path=self._PORTAL_PATH,
                interface=self._PORTAL_IFACE,
                member="OpenPipeWireRemote",
                signature="oa{sv}",
                body=[session_handle, {}],
            )
        )
        if pw_reply.message_type == MessageType.ERROR:
            raise XDGPortalError(f"OpenPipeWireRemote failed: {pw_reply.error_name}")

        if not pw_reply.unix_fds:
            raise XDGPortalError("OpenPipeWireRemote did not return a PipeWire fd.")
        fd = os.dup(pw_reply.unix_fds[0])
        return fd, node_id

    def run_explicit_diagnostic(self) -> dict[str, object]:
        diag = PortalDiagnosticState(
            stages=[],
            last_success_stage="",
            failing_stage="",
            expected_bytes=self.width * self.height * 3,
            timeout_s=float(self._GSTREAMER_FIRST_FRAME_TIMEOUT_S),
        )
        diag.mark("portal service available", "ok")
        diag.mark("ScreenCast interface available", "ok")
        diag.mark("session created", "pending")
        diag.mark("source selection prompt shown / skipped / restored", "pending")
        diag.mark("user approved / cancelled / timed out", "pending")
        diag.mark("PipeWire node/stream received", "pending")
        diag.mark("GStreamer pipeline created", "pending")
        diag.mark("pipeline reached PAUSED/PLAYING", "pending")
        diag.mark("caps/format negotiated", "pending")
        diag.mark("first buffer received", "pending")
        diag.mark("first non-empty frame received", "pending")
        diag.mark("frame dimensions/stride/bytes validated", "pending")
        try:
            self.initialize()
            diag.mark("session created", "ok")
            diag.mark("source selection prompt shown / skipped / restored", "ok")
            diag.mark("user approved / cancelled / timed out", "ok")
            diag.mark("PipeWire node/stream received", "ok")
            diag.mark("GStreamer pipeline created", "ok" if self._use_gstreamer else "skipped", "pipewire-python path active")
            diag.mark("pipeline reached PAUSED/PLAYING", "ok")
            caps_detail = str(self._last_frame_diag.get("caps") or "unknown")
            diag.mark("caps/format negotiated", "ok", caps_detail)
            frame = self.capture()
            diag.sample_received = bool(self._last_frame_diag.get("sample_received"))
            diag.buffer_present = bool(self._last_frame_diag.get("buffer_present"))
            diag.buffer_reported_size = int(self._last_frame_diag.get("buffer_reported_size") or 0)
            diag.memory_count = int(self._last_frame_diag.get("memory_count") or 0)
            diag.mapped_memory_size = int(self._last_frame_diag.get("mapped_memory_size") or 0)
            diag.stride = self._last_frame_diag.get("stride") if isinstance(self._last_frame_diag.get("stride"), int) else None
            diag.pts_ns = self._last_frame_diag.get("pts_ns") if isinstance(self._last_frame_diag.get("pts_ns"), int) else None
            diag.dts_ns = self._last_frame_diag.get("dts_ns") if isinstance(self._last_frame_diag.get("dts_ns"), int) else None
            diag.duration_ns = (
                self._last_frame_diag.get("duration_ns")
                if isinstance(self._last_frame_diag.get("duration_ns"), int)
                else None
            )
            diag.negotiated_format = str(self._last_frame_diag.get("format") or "")
            diag.negotiated_width = int(self._last_frame_diag.get("width") or 0) or None
            diag.negotiated_height = int(self._last_frame_diag.get("height") or 0) or None
            diag.negotiated_framerate = str(self._last_frame_diag.get("framerate") or "unknown")
            diag.empty_buffer_count = int(self._last_frame_diag.get("empty_buffer_count") or self._empty_first_buffers)
            diag.non_empty_buffer_count = int(
                self._last_frame_diag.get("non_empty_buffer_count") or self._non_empty_first_buffers
            )
            diag.mark("first buffer received", "ok" if diag.sample_received and diag.buffer_present else "failed")
            if frame.size <= 0:
                raise XDGPortalError("Empty frame payload after successful stream start.")
            diag.mark("first non-empty frame received", "ok")
            expected_bytes = self.width * self.height * 3
            received_bytes = int(frame.nbytes)
            diag.expected_bytes = expected_bytes
            diag.received_bytes = received_bytes
            if received_bytes < expected_bytes:
                raise XDGPortalError(
                    f"Frame bytes too small for negotiated dimensions (received={received_bytes}, expected={expected_bytes})."
                )
            diag.mark("frame dimensions/stride/bytes validated", "ok")
            return {
                "selected_backend": "xdg-portal",
                "mode": "explicit-test",
                "status": "tested",
                "reason": "explicit xdg-portal test completed",
                "sample_count": 1,
                "median_ms": None,
                "p95_ms": None,
                "jitter_ms": None,
                "score": None,
                "timed_out": False,
                "stages": diag.stages,
                "last_success_stage": diag.last_success_stage,
                "failing_stage": "",
                "details": {
                    "expected_bytes": diag.expected_bytes,
                    "received_bytes": diag.received_bytes,
                    "caps": f"RGB {self.width}x{self.height}",
                    "sample_received": diag.sample_received,
                    "buffer_present": diag.buffer_present,
                    "buffer_reported_size": diag.buffer_reported_size,
                    "memory_count": diag.memory_count,
                    "mapped_memory_size": diag.mapped_memory_size,
                    "caps": self._last_frame_diag.get("caps"),
                    "width": diag.negotiated_width or self.width,
                    "height": diag.negotiated_height or self.height,
                    "format": diag.negotiated_format,
                    "framerate": diag.negotiated_framerate,
                    "caps_metadata_warning": self._last_frame_diag.get("caps_metadata_warning"),
                    "stride": diag.stride,
                    "pts_ns": diag.pts_ns,
                    "dts_ns": diag.dts_ns,
                    "duration_ns": diag.duration_ns,
                    "first_frame_timeout_s": self._GSTREAMER_FIRST_FRAME_TIMEOUT_S,
                    "empty_buffer_count": diag.empty_buffer_count,
                    "non_empty_buffer_count": diag.non_empty_buffer_count,
                },
            }
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            failing_stage = "session created"
            if "SelectSources" in message or "source selection" in message:
                failing_stage = "source selection prompt shown / skipped / restored"
            elif "Start denied" in message:
                failing_stage = "user approved / cancelled / timed out"
            elif "OpenPipeWireRemote" in message or "PipeWire" in message:
                failing_stage = "PipeWire node/stream received"
            elif "GStreamer" in message:
                failing_stage = "first non-empty frame received"
            elif "Frame bytes too small" in message:
                failing_stage = "frame dimensions/stride/bytes validated"
            diag.mark(failing_stage, "failed", message)
            reason = message
            if "produced empty buffers" in message:
                reason = (
                    "PipeWire stream opened but produced empty buffers; likely format negotiation or portal stream issue."
                )
            return {
                "selected_backend": None,
                "mode": "explicit-test",
                "status": "failed",
                "reason": reason,
                "sample_count": 0,
                "median_ms": None,
                "p95_ms": None,
                "jitter_ms": None,
                "score": None,
                "timed_out": "timed out" in message.lower(),
                "stages": diag.stages,
                "last_success_stage": diag.last_success_stage,
                "failing_stage": failing_stage,
                "details": {
                    "expected_bytes": diag.expected_bytes,
                    "received_bytes": int(self._last_frame_diag.get("buffer_reported_size") or 0),
                    "sample_received": bool(self._last_frame_diag.get("sample_received")),
                    "buffer_present": bool(self._last_frame_diag.get("buffer_present")),
                    "buffer_reported_size": int(self._last_frame_diag.get("buffer_reported_size") or 0),
                    "memory_count": int(self._last_frame_diag.get("memory_count") or 0),
                    "mapped_memory_size": int(self._last_frame_diag.get("mapped_memory_size") or 0),
                    "caps": self._last_frame_diag.get("caps"),
                    "width": int(self._last_frame_diag.get("width") or self.width),
                    "height": int(self._last_frame_diag.get("height") or self.height),
                    "format": self._last_frame_diag.get("format"),
                    "framerate": self._last_frame_diag.get("framerate") or "unknown",
                    "caps_metadata_warning": self._last_frame_diag.get("caps_metadata_warning"),
                    "stride": self._last_frame_diag.get("stride"),
                    "pts_ns": self._last_frame_diag.get("pts_ns"),
                    "dts_ns": self._last_frame_diag.get("dts_ns"),
                    "duration_ns": self._last_frame_diag.get("duration_ns"),
                    "first_frame_timeout_s": self._GSTREAMER_FIRST_FRAME_TIMEOUT_S,
                    "empty_buffer_count": int(self._last_frame_diag.get("empty_buffer_count") or self._empty_first_buffers),
                    "non_empty_buffer_count": int(
                        self._last_frame_diag.get("non_empty_buffer_count") or self._non_empty_first_buffers
                    ),
                },
            }
        finally:
            self.close()

    def _open_pipewire_stream(self, fd: int, node_id: int) -> None:
        supported, reason = self._pipewire_python_is_supported()
        if not supported:
            logger.info(
                "pipewire-python capture path unsupported (%s); falling back to GStreamer.",
                reason,
            )
            self._open_via_gstreamer(fd, node_id)
            return

        try:
            self._open_via_pipewire_python(fd, node_id)
        except (ImportError, AttributeError, TypeError) as exc:
            logger.warning(
                "pipewire-python stream initialization failed (%s: %s); "
                "falling back to GStreamer.",
                type(exc).__name__,
                exc,
            )
            self._open_via_gstreamer(fd, node_id)

    def _pipewire_python_is_supported(self) -> tuple[bool, str]:
        try:
            import pipewire as pw  # type: ignore
        except ImportError as exc:
            return False, f"import failed: {exc}"

        required_symbols = ("MainLoop", "Context", "Stream", "SpaPod", "Direction", "StreamFlags")
        missing_symbols = [name for name in required_symbols if getattr(pw, name, None) is None]
        if missing_symbols:
            return False, f"missing symbols: {', '.join(missing_symbols)}"

        spa_pod_from_dict = getattr(pw.SpaPod, "from_dict", None)
        if spa_pod_from_dict is None:
            return False, "missing symbol: SpaPod.from_dict"

        return True, "supported"

    def _open_via_pipewire_python(self, fd: int, node_id: int) -> None:
        import pipewire as pw  # type: ignore

        self._pw_main_loop = pw.MainLoop()
        self._pw_context = pw.Context(self._pw_main_loop)
        self._pw_core = self._pw_context.connect_fd(fd)
        self._pw_stream = pw.Stream(
            self._pw_core,
            "nanoleaf-capture",
            pw.Properties(
                {
                    "media.type": "Video",
                    "media.category": "Capture",
                    "media.role": "Screen",
                }
            ),
        )

        params = [
            pw.SpaPod.from_dict(
                {
                    "video.format": "RGB",
                    "video.size": {"width": self.width, "height": self.height},
                }
            )
        ]
        self._pw_stream.connect(
            pw.Direction.INPUT,
            node_id,
            pw.StreamFlags.AUTOCONNECT | pw.StreamFlags.MAP_BUFFERS,
            params,
        )
        self._pw_main_loop.run_in_thread()
        self._use_gstreamer = False

    def _open_via_gstreamer(self, fd: int, node_id: int) -> None:
        from gi.repository import Gst

        Gst.init(None)
        errors: list[str] = []
        self._last_frame_diag = {}
        self._empty_first_buffers = 0
        self._non_empty_first_buffers = 0

        for fmt in self._APP_SINK_FORMATS:
            pipeline_desc = (
                f"pipewiresrc fd={fd} path={node_id} do-timestamp=true "
                "! queue leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=0 "
                "! videoconvert ! videoscale "
                f"! video/x-raw,width={self.width},height={self.height},format={fmt} "
                "! appsink name=sink emit-signals=false sync=false max-buffers=2 drop=true"
            )
            try:
                pipeline = Gst.parse_launch(pipeline_desc)
                appsink = pipeline.get_by_name("sink")
                if appsink is None:
                    raise XDGPortalError("GStreamer appsink was not created.")
                ret = pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    raise XDGPortalError(f"GStreamer failed to start with format={fmt}.")
                frame, diag = self._pull_gst_frame(appsink, timeout_s=self._GSTREAMER_FIRST_FRAME_TIMEOUT_S)
                self._last_frame_diag = diag
                if frame is not None:
                    self._gst_pipeline = pipeline
                    self._gst_sink = appsink
                    self._use_gstreamer = True
                    return
                pipeline.set_state(Gst.State.NULL)
                errors.append(f"{fmt}: {self._describe_gst_pull_failure(diag)}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fmt}: {exc}")
                try:
                    pipeline.set_state(Gst.State.NULL)
                except Exception:
                    pass

        raise XDGPortalError(
            "Portal stream negotiated, but no CPU-readable frame was received. "
            f"format_attempts={'; '.join(errors)}"
        )

    def _describe_gst_pull_failure(self, diag: dict[str, object]) -> str:
        warning = diag.get("caps_metadata_warning")
        warning_text = f"; metadata parse warning={warning}" if warning else ""
        if not bool(diag.get("sample_received")):
            return f"no sample{warning_text}"
        if not bool(diag.get("buffer_present")):
            return f"no buffer{warning_text}"
        if diag.get("map_attempted") and not bool(diag.get("map_success")):
            return f"map failure{warning_text}"
        if int(diag.get("buffer_reported_size") or 0) <= 0 or int(diag.get("mapped_memory_size") or 0) <= 0:
            return f"zero-byte buffer{warning_text}"
        if diag.get("rgb_conversion_attempted") and not bool(diag.get("rgb_conversion_success")):
            fmt = diag.get("format") or "unknown"
            return f"unsupported pixel format ({fmt}){warning_text}"
        return f"no CPU-readable frame{warning_text}"

    def _read_pipewire_frame(self) -> Optional[np.ndarray]:
        if self._use_gstreamer:
            return self._read_frame_gstreamer()
        return self._read_frame_pipewire_python()

    def _read_frame_pipewire_python(self) -> Optional[np.ndarray]:
        buf = self._pw_stream.dequeue_buffer()
        if buf is None:
            return None
        data = bytes(buf.datas[0].data[: self.width * self.height * 3])
        self._pw_stream.queue_buffer(buf)
        return np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3).copy()

    def _read_frame_gstreamer(self) -> Optional[np.ndarray]:
        sink = getattr(self, "_gst_sink", None)
        if sink is None:
            return None
        frame, diag = self._pull_gst_frame(sink, timeout_s=1.0)
        self._last_frame_diag = diag
        return frame

    def _pull_gst_frame(self, appsink, *, timeout_s: float) -> tuple[Optional[np.ndarray], dict[str, object]]:
        from gi.repository import Gst, GstVideo

        deadline = time.monotonic() + max(0.01, timeout_s)
        empty_buffers = self._empty_first_buffers
        non_empty_buffers = self._non_empty_first_buffers
        last_diag: dict[str, object] = {
            "sample_received": False,
            "buffer_present": False,
            "buffer_reported_size": 0,
            "memory_count": 0,
            "mapped_memory_size": 0,
            "caps": None,
            "width": 0,
            "height": 0,
            "format": None,
            "framerate": None,
            "caps_metadata_warning": None,
            "stride": None,
            "pts_ns": None,
            "dts_ns": None,
            "duration_ns": None,
            "map_attempted": False,
            "map_success": False,
            "rgb_conversion_attempted": False,
            "rgb_conversion_success": False,
            "empty_buffer_count": empty_buffers,
            "non_empty_buffer_count": non_empty_buffers,
        }

        while time.monotonic() < deadline:
            timeout_ns = int(self._GSTREAMER_FIRST_FRAME_POLL_INTERVAL_S * 1_000_000_000)
            sample = (
                appsink.try_pull_sample(timeout_ns)
                if hasattr(appsink, "try_pull_sample")
                else appsink.emit("try-pull-sample", timeout_ns)
            )
            if sample is None:
                time.sleep(self._GSTREAMER_FIRST_FRAME_POLL_INTERVAL_S)
                continue
            last_diag["sample_received"] = True
            caps = sample.get_caps()
            last_diag.update(self._extract_caps_metadata(caps, GstVideo=GstVideo))

            buffer = sample.get_buffer()
            if buffer is None:
                continue
            last_diag["buffer_present"] = True
            last_diag["buffer_reported_size"] = int(buffer.get_size())
            last_diag["memory_count"] = int(buffer.n_memory())
            last_diag["pts_ns"] = int(buffer.pts) if int(buffer.pts) >= 0 else None
            last_diag["dts_ns"] = int(buffer.dts) if int(buffer.dts) >= 0 else None
            last_diag["duration_ns"] = int(buffer.duration) if int(buffer.duration) >= 0 else None

            last_diag["map_attempted"] = True
            mapped, map_info = buffer.map(Gst.MapFlags.READ)
            if not mapped:
                last_diag["map_success"] = False
                empty_buffers += 1
                last_diag["empty_buffer_count"] = empty_buffers
                continue
            last_diag["map_success"] = True
            try:
                mapped_size = int(getattr(map_info, "size", 0))
                last_diag["mapped_memory_size"] = mapped_size
                if mapped_size <= 0:
                    empty_buffers += 1
                    last_diag["empty_buffer_count"] = empty_buffers
                    if empty_buffers >= self._MAX_EMPTY_FIRST_BUFFERS:
                        self._empty_first_buffers = empty_buffers
                        self._non_empty_first_buffers = non_empty_buffers
                        return None, last_diag
                    continue
                last_diag["rgb_conversion_attempted"] = True
                frame = self._mapped_bytes_to_rgb(
                    payload=bytes(map_info.data),
                    width=int(last_diag["width"] or self.width),
                    height=int(last_diag["height"] or self.height),
                    fmt=str(last_diag["format"] or "RGB"),
                    stride=(
                        int(last_diag["stride"])
                        if isinstance(last_diag.get("stride"), int) and int(last_diag["stride"]) > 0
                        else None
                    ),
                )
                if frame is not None:
                    last_diag["rgb_conversion_success"] = True
                    non_empty_buffers += 1
                    last_diag["non_empty_buffer_count"] = non_empty_buffers
                    self._empty_first_buffers = empty_buffers
                    self._non_empty_first_buffers = non_empty_buffers
                    return frame, last_diag
                last_diag["rgb_conversion_success"] = False
            finally:
                buffer.unmap(map_info)

        self._empty_first_buffers = empty_buffers
        self._non_empty_first_buffers = non_empty_buffers
        return None, last_diag

    def _extract_caps_metadata(self, caps, *, GstVideo) -> dict[str, object]:
        metadata: dict[str, object] = {
            "caps": None,
            "width": 0,
            "height": 0,
            "format": None,
            "framerate": None,
            "stride": None,
            "caps_metadata_warning": None,
        }
        warnings: list[str] = []
        if caps is None:
            return metadata
        caps_str: str | None = None
        try:
            caps_str = caps.to_string()
            metadata["caps"] = caps_str
        except Exception as exc:  # noqa: BLE001
            warnings.append(str(exc))
        try:
            if caps.get_size() > 0:
                structure = caps.get_structure(0)
                ok_width, width = structure.get_int("width")
                if ok_width:
                    metadata["width"] = int(width)
                ok_height, height = structure.get_int("height")
                if ok_height:
                    metadata["height"] = int(height)
                fmt = structure.get_string("format")
                if fmt is not None:
                    metadata["format"] = str(fmt)
                try:
                    ok_fps, fps_num, fps_den = structure.get_fraction("framerate")
                    if ok_fps:
                        metadata["framerate"] = f"{int(fps_num)}/{int(fps_den)}"
                    else:
                        metadata["framerate"] = "unknown"
                except Exception as exc:  # noqa: BLE001
                    metadata["framerate"] = "unknown"
                    warnings.append(str(exc))
                if caps_str is not None:
                    cached_vi = self._caps_video_info_cache.get(caps_str)
                    if cached_vi is not None:
                        metadata["stride"] = int(cached_vi)
                    else:
                        try:
                            video_info = GstVideo.VideoInfo.new_from_caps(caps)
                            if video_info is not None:
                                stride_val = int(video_info.stride[0])
                                metadata["stride"] = stride_val
                                self._caps_video_info_cache[caps_str] = stride_val
                                if len(self._caps_video_info_cache) > self._caps_video_info_cache_max:
                                    self._caps_video_info_cache.pop(next(iter(self._caps_video_info_cache)))
                        except Exception:
                            pass
        except Exception as exc:  # noqa: BLE001
            warnings.append(str(exc))
        if warnings:
            metadata["caps_metadata_warning"] = "; ".join(filter(None, warnings))
        return metadata

    def _mapped_bytes_to_rgb(
        self,
        *,
        payload: bytes,
        width: int,
        height: int,
        fmt: str,
        stride: int | None,
    ) -> Optional[np.ndarray]:
        channels = 3 if fmt in {"RGB", "BGR"} else 4 if fmt in {"RGBx", "BGRx", "RGBA", "BGRA"} else 0
        if channels <= 0 or width <= 0 or height <= 0:
            return None
        min_stride = width * channels
        row_stride = max(min_stride, int(stride or 0))
        expected = row_stride * height
        if len(payload) < expected:
            return None
        frame2d = np.frombuffer(payload[:expected], dtype=np.uint8).reshape(height, row_stride)
        packed = frame2d[:, : min_stride].reshape(height, width, channels)
        if fmt == "RGB":
            return packed[:, :, :3].copy()
        if fmt == "BGR":
            return packed[:, :, [2, 1, 0]].copy()
        if fmt in {"RGBx", "RGBA"}:
            return packed[:, :, :3].copy()
        if fmt in {"BGRx", "BGRA"}:
            return packed[:, :, [2, 1, 0]].copy()
        return None

    def _close_pipewire_stream(self) -> None:
        if self._use_gstreamer:
            pipeline = getattr(self, "_gst_pipeline", None)
            if pipeline is not None:
                try:
                    from gi.repository import Gst

                    pipeline.set_state(Gst.State.NULL)
                except Exception:
                    pass
            self._gst_pipeline = None
            self._gst_sink = None
            return

        loop = getattr(self, "_pw_main_loop", None)
        if loop is not None:
            loop.quit()

    async def _close_portal_session(self, session_handle: str) -> None:
        from dbus_next import Message

        bus = self._portal_bus
        owns_bus = False
        if bus is None:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            owns_bus = True
        try:
            await bus.call(
                Message(
                    destination=self._PORTAL_BUS,
                    path=session_handle,
                    interface=self._SESSION_IFACE,
                    member="Close",
                )
            )
        finally:
            if owns_bus:
                disconnect = getattr(bus, "disconnect", None)
                if disconnect is not None:
                    maybe = disconnect()
                    if asyncio.iscoroutine(maybe):
                        await maybe
            else:
                self._portal_bus = None
                disconnect = getattr(bus, "disconnect", None)
                if disconnect is not None:
                    maybe = disconnect()
                    if asyncio.iscoroutine(maybe):
                        await maybe

    def _close_portal_session_sync(self) -> None:
        if not self._session_handle:
            return

        session_handle = self._session_handle
        self._session_handle = None
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._close_portal_session(session_handle))
                return

            error: BaseException | None = None

            def _worker() -> None:
                nonlocal error
                try:
                    asyncio.run(self._close_portal_session(session_handle))
                except BaseException as exc:  # pragma: no cover - defensive fallback
                    error = exc

            thread = threading.Thread(target=_worker, name="portal-close-session", daemon=True)
            thread.start()
            thread.join()
            if error is not None:
                raise error
        except Exception:
            pass

    def _load_restore_token(self) -> Optional[str]:
        try:
            return self._token_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _save_restore_token(self, token: str) -> None:
        try:
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(token, encoding="utf-8")
        except OSError:
            pass
