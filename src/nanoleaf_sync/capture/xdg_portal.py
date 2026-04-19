"""XDG ScreenCast portal capture backend.

Uses org.freedesktop.portal.ScreenCast for compositor-agnostic Wayland capture.
The backend negotiates a portal session over D-Bus and then consumes frames via
PipeWire. A restore token is persisted so users are not repeatedly prompted.
"""

from __future__ import annotations

import asyncio
import os
import random
import threading
from pathlib import Path
from typing import Optional

import numpy as np


class XDGPortalError(RuntimeError):
    """Raised when portal negotiation or PipeWire capture fails."""


class XDGPortalCapture:
    """Screen capture via org.freedesktop.portal.ScreenCast + PipeWire."""

    name = "xdg-portal"

    _PORTAL_BUS = "org.freedesktop.portal.Desktop"
    _PORTAL_PATH = "/org/freedesktop/portal/desktop"
    _PORTAL_IFACE = "org.freedesktop.portal.ScreenCast"
    _SESSION_IFACE = "org.freedesktop.portal.Session"
    _REQUEST_IFACE = "org.freedesktop.portal.Request"

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
        self._initialized = False
        self._use_gstreamer = False

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

        worker = threading.Thread(target=_worker, daemon=True)
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
        sender = bus.unique_name.replace(".", "_").lstrip(":")

        async def _call(method: str, signature: str, body: list, *, handle_token: str):
            request_path = (
                f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"
            )
            future: asyncio.Future = asyncio.get_event_loop().create_future()

            def _on_signal(msg):
                if (
                    msg.path == request_path
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
                if reply.message_type == MessageType.ERROR:
                    raise XDGPortalError(
                        f"Portal {method} call failed: {reply.error_name}"
                    )
                return await asyncio.wait_for(future, timeout=120.0)
            finally:
                bus.remove_message_handler(_on_signal)

        session_token = f"nanoleaf_{random.randint(10000, 99999)}"
        handle_token = f"h{random.randint(10000, 99999)}"
        create_options: dict[str, Variant] = {
            "handle_token": Variant("s", handle_token),
            "session_handle_token": Variant("s", session_token),
        }
        msg = await _call(
            "CreateSession", "a{sv}", [create_options], handle_token=handle_token
        )
        response_code = msg.body[0]
        if response_code != 0:
            raise XDGPortalError(f"CreateSession denied (response={response_code}).")
        session_handle = msg.body[1]["session_handle"].value
        self._session_handle = str(session_handle)

        restore_token = self._load_restore_token()
        handle_token2 = f"h{random.randint(10000, 99999)}"
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

        handle_token3 = f"h{random.randint(10000, 99999)}"
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
            value = new_restore.value if hasattr(new_restore, "value") else new_restore
            self._save_restore_token(str(value))

        first_stream = streams.value[0] if hasattr(streams, "value") else streams[0]
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
        disconnect = getattr(bus, "disconnect", None)
        if disconnect is not None:
            maybe = disconnect()
            if asyncio.iscoroutine(maybe):
                await maybe
        return fd, node_id

    def _open_pipewire_stream(self, fd: int, node_id: int) -> None:
        try:
            self._open_via_pipewire_python(fd, node_id)
        except ImportError:
            self._open_via_gstreamer(fd, node_id)

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
        import mmap
        import subprocess
        import tempfile

        self._shm_file = tempfile.NamedTemporaryFile(delete=False, suffix=".raw")
        frame_bytes = self.width * self.height * 3
        self._shm_file.write(b"\x00" * frame_bytes)
        self._shm_file.flush()

        cmd = [
            "gst-launch-1.0",
            "-q",
            "pipewiresrc",
            f"fd={fd}",
            f"path={node_id}",
            "!",
            "videoconvert",
            "!",
            f"video/x-raw,format=RGB,width={self.width},height={self.height}",
            "!",
            "filesink",
            f"location={self._shm_file.name}",
            "append=false",
        ]
        self._gst_proc = subprocess.Popen(cmd, close_fds=True, pass_fds=(fd,))
        self._shm_mm = mmap.mmap(self._shm_file.fileno(), frame_bytes)
        self._frame_bytes = frame_bytes
        self._use_gstreamer = True

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
        self._shm_mm.seek(0)
        raw = self._shm_mm.read(self._frame_bytes)
        if len(raw) < self._frame_bytes:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 3).copy()

    def _close_pipewire_stream(self) -> None:
        if self._use_gstreamer:
            proc = getattr(self, "_gst_proc", None)
            if proc is not None:
                proc.terminate()
            mm = getattr(self, "_shm_mm", None)
            if mm is not None:
                mm.close()
            f = getattr(self, "_shm_file", None)
            if f is not None:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass
            return

        loop = getattr(self, "_pw_main_loop", None)
        if loop is not None:
            loop.quit()

    async def _close_portal_session(self, session_handle: str) -> None:
        from dbus_next import Message
        from dbus_next.aio import MessageBus

        bus = await MessageBus().connect()
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

            thread = threading.Thread(target=_worker, daemon=True)
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
