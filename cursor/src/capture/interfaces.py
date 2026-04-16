from __future__ import annotations

from typing import Protocol

import numpy as np


class CaptureBackend(Protocol):
    """
    Typed contract for screen capture backends used by the runtime.

    Required:
    - ``capture()`` returns an RGB frame with shape ``(H, W, 3)``.

    Optional status metadata:
    - ``name``: backend identifier (e.g. ``"mock"``, ``"replay"``, ``"kmsgrab"``)
    - ``last_capture_path``: concrete path used for recent frame production
      (e.g. ``"drm-kms"`` or ``"kwin-dbus"`` for fallback reporting)
    """

    name: str
    last_capture_path: str | None

    def capture(self) -> np.ndarray: ...
