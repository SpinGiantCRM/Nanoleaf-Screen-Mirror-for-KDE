"""
Capture package.

Authoritative runtime path:
    from capture.factory import create_capture_backend

The legacy `screen_capture` module (ScreenCapture, DRMKMSCaptureBackend,
KWinDBusCaptureBackend) is kept for backwards compatibility but is not used
by the service pipeline. Prefer the factory and concrete backend modules below.
"""

from .kmsgrab import KMSGrabCapture, KMSGrabError
from .kwin_dbus import KWinDBusScreenshotCapture
from .mock_capture import MockScreenCapture
from .factory import create_capture_backend

# Legacy exports — imported lazily to avoid emitting DeprecationWarning at
# every `import capture` call. Import directly from capture.screen_capture
# if you need them.
def __getattr__(name):  # noqa: N807
    _legacy = (
        "BackendUnavailableError",
        "CaptureBackendError",
        "DRMKMSCaptureBackend",
        "KWinDBusCaptureBackend",
        "ScreenCapture",
    )
    if name in _legacy:
        import warnings
        warnings.warn(
            f"capture.{name} is from the deprecated screen_capture module. "
            "Use capture.factory.create_capture_backend() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from . import screen_capture as _sc  # noqa: PLC0415
        return getattr(_sc, name)
    raise AttributeError(f"module 'capture' has no attribute {name!r}")


__all__ = [
    # Authoritative runtime path
    "create_capture_backend",
    # Concrete backends
    "KMSGrabCapture",
    "KMSGrabError",
    "KWinDBusScreenshotCapture",
    "MockScreenCapture",
    # Legacy (deprecated) — available via __getattr__
    "BackendUnavailableError",
    "CaptureBackendError",
    "DRMKMSCaptureBackend",
    "KWinDBusCaptureBackend",
    "ScreenCapture",
]
