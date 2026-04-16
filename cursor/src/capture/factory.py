from __future__ import annotations

from .kmsgrab import KMSGrabCapture
from .kwin_dbus import KWinDBusScreenshotCapture
from .mock_capture import MockScreenCapture
from .replay_capture import ReplayScreenCapture


def create_capture_backend(
    *,
    width: int,
    height: int,
    use_mock_capture: bool,
    prefer_backend: str,
    allow_fallback: bool,
    hdr_max_nits: float,
    hdr_transfer: str,
    hdr_primaries: str,
    replay_frames_path: str | None = None,
) -> object:
    """
    Create the capture backend used by the runtime service.

    This factory is the single source of truth for capture selection, so
    tests and the service cannot diverge.
    """

    if use_mock_capture:
        return MockScreenCapture(width=width, height=height)

    if prefer_backend == "replay":
        if not replay_frames_path:
            raise ValueError("prefer_backend='replay' requires replay_frames_path")
        return ReplayScreenCapture(
            width=width,
            height=height,
            frames_path=replay_frames_path,
        )

    if prefer_backend in ("kwin-dbus", "kwin-dbus-screenshot"):
        return KWinDBusScreenshotCapture(width=width, height=height)

    # Default: kmsgrab-style backend with optional fallback.
    return KMSGrabCapture(
        width=width,
        height=height,
        hdr_max_nits=hdr_max_nits,
        hdr_transfer=hdr_transfer,
        hdr_primaries=hdr_primaries,
        allow_fallback=allow_fallback,
    )
