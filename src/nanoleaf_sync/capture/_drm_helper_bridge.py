from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import socket
import struct
import subprocess  # nosec B404
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from nanoleaf_sync.tools.setcap_helper import (
    caps_required_for_helper,
    ensure_helper_caps,
    helper_binary_sha256,
    helper_has_required_caps,
    read_stored_helper_hash,
    store_helper_hash,
)

_log = logging.getLogger(__name__)

_MMAP_INFO_STRUCT = struct.Struct("=QQIIIIIII")
_HELPER_TIMEOUT_SECONDS = 5.0
_HELPER_POLL_SECONDS = 0.05
_MODIFIER_VENDOR_NVIDIA = 0x03


@dataclass(frozen=True)
class DRMHelperMmapInfo:
    pass_fd: int
    offset: int
    size: int
    pitch: int
    fourcc: int
    fb_id: int
    width: int
    height: int
    modifier: int
    is_dma_buf: bool


def is_nvidia_x_tiled_modifier(modifier: int) -> bool:
    if modifier in {0, 1 << 56}:
        return False
    return ((int(modifier) >> 56) & 0xFF) == _MODIFIER_VENDOR_NVIDIA


def _helper_binary_path() -> Path | None:
    module_dir = Path(__file__).resolve().parent
    candidates = (
        module_dir / "nanoleaf_drm_helper",
        module_dir / "bin" / "nanoleaf_drm_helper",
        Path(os.environ.get("NANOLEAF_DRM_HELPER", "")).expanduser(),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _fd_is_dma_buf(fd: int) -> bool:
    try:
        link = os.readlink(f"/proc/self/fd/{int(fd)}")
    except OSError:
        return True
    if "dmabuf" in link or link.startswith("anon_inode:"):
        return True
    return "/dev/dri/card" not in link


def _helper_launch_allowed(helper: Path) -> bool:
    if not helper.is_file() or not os.access(helper, os.X_OK):
        return False
    if not caps_required_for_helper(helper):
        return True
    if helper_has_required_caps(helper):
        store_helper_hash(helper)
        return True
    current_hash = helper_binary_sha256(helper)
    stored_hash = read_stored_helper_hash()
    if stored_hash is not None and stored_hash != current_hash:
        _log.warning("DRM helper binary hash changed and capabilities are missing; refusing launch")
        ensure_helper_caps(helper, show_dialog=False)
        return False
    if stored_hash == current_hash:
        _log.warning("DRM helper capabilities missing for unchanged binary; refusing launch")
        return False
    _log.warning("DRM helper capabilities missing for new binary; refusing launch")
    ensure_helper_caps(helper, show_dialog=False)
    return False


def request_helper_mmap(*, card_path: str, fb_id: int = 0) -> DRMHelperMmapInfo | None:
    helper = _helper_binary_path()
    if helper is None:
        return None
    if not _helper_launch_allowed(helper):
        return None

    sock_path = os.path.join(
        tempfile.gettempdir(),
        f"nanoleaf_drm_{os.getpid()}_{int(fb_id)}.sock",
    )
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        server.bind(sock_path)
        server.listen(1)
        server.settimeout(_HELPER_TIMEOUT_SECONDS)

        proc = subprocess.Popen(  # nosec B603
            [str(helper), card_path, sock_path, str(int(fb_id))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        conn = _accept_helper_connection(server, proc)
        if conn is None:
            stdout, stderr = proc.communicate(timeout=0.2)
            _log.debug(
                "DRM helper did not connect for fb %s: rc=%s stdout=%r stderr=%r",
                fb_id,
                proc.returncode,
                stdout,
                stderr,
            )
            return None
        with conn:
            payload, fds = _recv_payload_with_fds(conn, _MMAP_INFO_STRUCT.size)
        stdout, stderr = proc.communicate(timeout=_HELPER_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            _log.debug(
                "DRM helper failed for fb %s: rc=%s stdout=%r stderr=%r",
                fb_id,
                proc.returncode,
                stdout,
                stderr,
            )
            return None
        if not fds:
            _log.debug("DRM helper returned no file descriptors for fb %s", fb_id)
            return None
        (
            offset,
            size,
            pitch,
            fourcc,
            reply_fb_id,
            width,
            height,
            modifier_lo,
            modifier_hi,
        ) = _MMAP_INFO_STRUCT.unpack(payload)
        if size <= 0 or pitch <= 0:
            return None
        pass_fd = int(fds[0])
        modifier = (int(modifier_hi) << 32) | int(modifier_lo)
        return DRMHelperMmapInfo(
            pass_fd=pass_fd,
            offset=int(offset),
            size=int(size),
            pitch=int(pitch),
            fourcc=int(fourcc),
            fb_id=int(reply_fb_id) if int(reply_fb_id) > 0 else int(fb_id),
            width=int(width),
            height=int(height),
            modifier=modifier,
            is_dma_buf=_fd_is_dma_buf(pass_fd),
        )
    except (OSError, subprocess.SubprocessError, struct.error, ValueError) as exc:
        _log.debug("DRM helper mmap request failed for fb %s: %s", fb_id, exc)
        return None
    finally:
        server.close()
        with contextlib.suppress(OSError):
            if os.path.exists(sock_path):
                os.unlink(sock_path)


def mmap_helper_framebuffer(info: DRMHelperMmapInfo, libc: ctypes.CDLL) -> tuple[int, int]:
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_long,
    ]
    mmap_fd = int(info.pass_fd)
    mmap_offset = 0 if info.is_dma_buf else int(info.offset)
    prot_read = 0x01
    map_shared = 0x01
    map_failed = ctypes.c_void_p(-1).value or -1
    ptr = libc.mmap(
        None,
        ctypes.c_size_t(info.size),
        ctypes.c_int(prot_read),
        ctypes.c_int(map_shared),
        ctypes.c_int(mmap_fd),
        ctypes.c_long(mmap_offset),
    )
    ptr_addr = ptr if isinstance(ptr, int) else int(ptr.value or 0)
    if ptr_addr == 0 or ptr_addr == map_failed:
        raise OSError("DRM helper mmap failed")
    return ptr_addr, int(info.size)


def _accept_helper_connection(
    server: socket.socket,
    proc: subprocess.Popen[str],
) -> socket.socket | None:
    deadline = time.monotonic() + _HELPER_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        remaining = max(0.0, deadline - time.monotonic())
        server.settimeout(min(_HELPER_POLL_SECONDS, remaining))
        try:
            conn, _addr = server.accept()
            return conn
        except OSError as exc:
            if isinstance(exc, socket.timeout) or exc.errno in {11, 35, 110, 115}:
                continue
            raise
    return None


def _recv_payload_with_fds(conn: socket.socket, size: int) -> tuple[bytes, list[int]]:
    chunks: list[bytes] = []
    remaining = size
    fds: list[int] = []
    while remaining > 0:
        msg = conn.recvmsg(remaining, socket.CMSG_SPACE(4))
        data, ancdata, _msg_flags, _addr = msg
        if not data:
            raise OSError("DRM helper socket closed before payload complete")
        chunks.append(data)
        remaining -= len(data)
        if ancdata and not fds:
            for level, ctype, cdata in ancdata:
                if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
                    fds.extend(struct.unpack("i" * (len(cdata) // 4), cdata[: len(cdata)]))
    return b"".join(chunks), fds
