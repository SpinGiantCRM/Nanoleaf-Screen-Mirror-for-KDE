from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class KWinDBusCaptureParams:
    width: int
    height: int
    # If None, the implementation will use the primary screen.
    # Monitor selection is intentionally left flexible because KDE/KWin
    # export different identifiers depending on version/compositor.
    monitor_id: Optional[str] = None


class KWinDBusScreenshotCapture:
    """
    KWin D-Bus screenshot capture (stub).

    Requirements:
    - acts as a fallback when the low-latency DRM/KMS path is unavailable
    - returns an RGB numpy array

    Note:
    The exact KWin D-Bus interface/method signatures differ across KDE Plasma
    versions. This file intentionally keeps the capture logic as a stub and
    includes an outline for the eventual real implementation using `dbus-next`
    or `pydbus`.
    """

    name = "kwin-dbus"

    def __init__(
        self, width: int, height: int, monitor_id: Optional[str] = None
    ) -> None:
        self.params = KWinDBusCaptureParams(
            width=width, height=height, monitor_id=monitor_id
        )
        self._black = np.zeros(
            (self.params.height, self.params.width, 3), dtype=np.uint8
        )

    def capture(self) -> np.ndarray:
        """
        Return an RGB frame as a numpy array.

        Stub behavior:
        - returns a black frame while the real D-Bus call is not implemented
        """

        # Keep call overhead small: just return a reusable buffer.
        # Later, replace this with a D-Bus screenshot call that yields pixel data.
        return self._black

    # ---- Outline for future real implementation ----
    def _try_capture_via_dbus(self) -> Optional[np.ndarray]:
        """
        Placeholder: future D-Bus screenshot implementation.

        Expected steps (outline only):
        1. Connect to session bus
        2. Call KWin screenshot API to retrieve image bytes (format: PNG or raw pixels)
        3. Decode/convert to RGB and reshape to (H, W, 3)
        """

        # Example of what the real code will do (intentionally not implemented):
        # from dbus_next.aio import MessageBus
        # bus = await MessageBus().connect()
        # proxy = bus.get_proxy_object('org.kde.KWin', '/Screenshot', interface)
        # raw_bytes = await proxy.call('captureScreen', ...)
        # ...decode to numpy...
        return None
