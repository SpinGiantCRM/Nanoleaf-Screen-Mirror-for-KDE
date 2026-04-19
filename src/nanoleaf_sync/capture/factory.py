from __future__ import annotations

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.capture.mock_capture import MockScreenCapture


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

    Recovery decision: keep one real backend (kwin-dbus) plus one development
    backend (mock). Any other backend requests are treated as configuration
    drift and fail fast with a clear error.
    """

    if use_mock_capture:
        return MockScreenCapture(width=width, height=height)

    normalized = (prefer_backend or "").strip().lower()
    if normalized in {"", "kwin-dbus", "kwin_dbus", "kwin-dbus-screenshot"}:
        return KWinDBusScreenshotCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )

    raise ValueError(
        "Unsupported capture backend. This recovered build supports only "
        "'kwin-dbus' for real capture (or mock capture for safe setup)."
    )
