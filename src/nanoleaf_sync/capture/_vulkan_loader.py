from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import numpy as np

_last_error = ""
_session: dict[str, Any] | None = None


def last_error() -> str:
    return str(_last_error or "")


def vulkan_available() -> bool:
    global _last_error
    if os.environ.get("NANOLEAF_VULKAN_FORCE_AVAILABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return True
    try:
        import ctypes
        import ctypes.util

        libname = ctypes.util.find_library("vulkan")
        if not libname:
            _last_error = "libvulkan_not_found"
            return False
        ctypes.CDLL(libname)
        return True
    except OSError as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        return False


def import_dma_buf_image(*, fd: int, width: int, height: int, pixel_format: str) -> bool:
    global _session, _last_error
    if fd < 0:
        _last_error = "invalid_dma_buf_fd"
        return False
    if not vulkan_available():
        return False
    _session = {
        "fd": int(fd),
        "width": int(width),
        "height": int(height),
        "pixel_format": str(pixel_format),
    }
    return True


def dispatch_zone_sampler(
    *,
    rects: Sequence[tuple[int, int, int, int]],
    width: int,
    height: int,
) -> np.ndarray:
    global _last_error
    if _session is None:
        _last_error = "vulkan_session_missing"
        raise RuntimeError(_last_error)
    out = np.zeros((len(rects), 3), dtype=np.uint8)
    _last_error = ""
    return out


def release() -> None:
    global _session
    _session = None
