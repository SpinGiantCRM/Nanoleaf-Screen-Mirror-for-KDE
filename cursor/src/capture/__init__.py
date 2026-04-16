from .factory import create_capture_backend
from .kmsgrab import KMSGrabCapture
from .kwin_dbus import KWinDBusScreenshotCapture
from .mock_capture import MockScreenCapture
from .replay_capture import ReplayScreenCapture

__all__ = [
    "KMSGrabCapture",
    "KWinDBusScreenshotCapture",
    "ReplayScreenCapture",
    "MockScreenCapture",
    "create_capture_backend",
]
