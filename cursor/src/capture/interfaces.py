from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class CaptureBackendProtocol(Protocol):
    """Required runtime contract for capture backends used by the service."""

    def capture(self) -> np.ndarray: ...

    def close(self) -> None: ...


@runtime_checkable
class CaptureStatusMetadataProtocol(Protocol):
    """
    Optional metadata surfaced by get_status().

    Backends may expose these fields to describe active backend/path details.
    """

    name: Optional[str]
    last_capture_path: Optional[str]
