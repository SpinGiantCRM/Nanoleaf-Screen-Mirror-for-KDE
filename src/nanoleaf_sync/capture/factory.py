from __future__ import annotations

from importlib import import_module
from functools import lru_cache
import os
from pathlib import Path

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture
from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.capture.mock_capture import MockScreenCapture
from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture


@lru_cache(maxsize=1)
def _has_drm_device() -> bool:
    card_path = os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0")
    return Path(card_path).exists()


@lru_cache(maxsize=1)
def _kmsgrab_bindings_available() -> bool:
    try:
        module = import_module("nanoleaf_sync.capture._kmsgrab")
        if callable(getattr(module, "capture_dma_buf_rgb", None)):
            return True
    except ImportError:
        pass

    try:
        module = import_module("kmsgrab")  # type: ignore
        return callable(getattr(module, "capture", None))
    except ImportError:
        return False


def _resolve_auto_backend() -> str:
    if _has_drm_device() and _kmsgrab_bindings_available():
        return "kmsgrab"
    return "kwin-dbus"


def _resolve_prefer_backend(prefer_backend: str) -> str:
    normalized = (prefer_backend or "").strip().lower()
    if normalized in {"", "auto"}:
        return _resolve_auto_backend()
    if normalized in {"kwin-dbus", "kwin_dbus", "kwin-dbus-screenshot"}:
        return "kwin-dbus"
    if normalized in {"xdg-portal", "xdg_portal", "portal"}:
        return "xdg-portal"
    if normalized in {"kmsgrab", "kms-grab", "drm-kms", "drm_kms"}:
        return "kmsgrab"
    return normalized


def create_capture_backend(
    *,
    width: int,
    height: int,
    use_mock_capture: bool,
    prefer_backend: str,
    hdr_max_nits: float = 1000.0,
    hdr_transfer: str = "srgb",
    hdr_primaries: str = "bt709",
) -> CaptureBackend:
    """Create capture backend for the runtime.

    Supports mock capture plus compositor-backed capture via KWin D-Bus or
    XDG desktop portal (ScreenCast + PipeWire).
    """

    if use_mock_capture:
        return MockScreenCapture(width=width, height=height)

    normalized = _resolve_prefer_backend(prefer_backend)
    if normalized == "kwin-dbus":
        return KWinDBusScreenshotCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )

    if normalized == "xdg-portal":
        return XDGPortalCapture(width=width, height=height)

    if normalized == "kmsgrab":
        return KMSGrabCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )

    raise ValueError(
        "Unsupported capture backend. Supported real backends are "
        "'kwin-dbus', 'xdg-portal', and 'kmsgrab' (or mock capture for safe setup)."
    )
