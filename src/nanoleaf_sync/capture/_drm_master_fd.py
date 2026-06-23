from __future__ import annotations

import ctypes
import logging
import os

_log = logging.getLogger(__name__)

_SYS_pidfd_open = 434
_SYS_pidfd_getfd = 438


def find_kwin_pid() -> int | None:
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm in ("kwin_wayland", "kwin_x11", "kwin"):
            return int(entry)
    return None


def clone_kwin_drm_fd(card_path: str = "/dev/dri/card0") -> int | None:
    kwin_pid = find_kwin_pid()
    if kwin_pid is None:
        _log.debug("KWin process not found")
        return None

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    fd_dir = f"/proc/{kwin_pid}/fd/"
    real_card = os.path.realpath(card_path)

    for fd_name in os.listdir(fd_dir):
        try:
            link = os.readlink(fd_dir + fd_name)
            if os.path.realpath(link) != real_card:
                continue
        except OSError:
            continue

        fd_num = int(fd_name)
        pidfd = libc.syscall(_SYS_pidfd_open, ctypes.c_int(kwin_pid), ctypes.c_int(0))
        if pidfd < 0:
            continue
        cloned = libc.syscall(
            _SYS_pidfd_getfd, ctypes.c_int(pidfd), ctypes.c_int(fd_num), ctypes.c_int(0)
        )
        os.close(pidfd)
        if cloned >= 0:
            _log.debug("cloned KWin fd %s -> %s (pid=%s)", fd_num, cloned, kwin_pid)
            return int(cloned)

    _log.debug("no KWin DRM fd cloned (pid=%s)", kwin_pid)
    return None
