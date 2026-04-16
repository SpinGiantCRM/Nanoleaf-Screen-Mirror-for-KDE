"""
DEPRECATED: Legacy capture abstraction.

This module predates the `capture.factory` / backend path that the service
and tests actually use. It is kept here temporarily to avoid breaking any
external code that may import from it, but it is not used by the runtime
pipeline and will be removed in a future cleanup pass.

Authoritative capture path:
    capture.factory.create_capture_backend(...)

Do not add new features here. If you need a new capture backend, add it as
a standalone module under `capture/` and wire it into `capture/factory.py`.
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "capture.screen_capture is deprecated and unused by the runtime pipeline. "
    "Use capture.factory.create_capture_backend() instead.",
    DeprecationWarning,
    stacklevel=2,
)

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np


class CaptureBackendError(RuntimeError):
    """Raised when a capture backend cannot produce a frame."""


class BackendUnavailableError(CaptureBackendError):
    """Raised when a backend is unsupported or cannot initialize."""


@dataclass(frozen=True)
class FrameSpec:
    """Describes the expected in-memory frame layout."""

    width: int
    height: int
    channels: int = 3
    dtype: np.dtype = np.uint8

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.height, self.width, self.channels)


class CaptureBackend(ABC):
    """Shared interface for low-latency screen capture backends."""

    name: str = "unknown"

    def __init__(self, frame_spec: FrameSpec) -> None:
        self.frame_spec = frame_spec
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        self._open()
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            return
        self._close()
        self._opened = False

    def capture(self) -> np.ndarray:
        if not self._opened:
            self.open()
        frame = self._capture()
        if frame.dtype != self.frame_spec.dtype:
            frame = frame.astype(self.frame_spec.dtype, copy=False)
        return frame

    @abstractmethod
    def _open(self) -> None:
        """Initialize backend resources."""

    @abstractmethod
    def _capture(self) -> np.ndarray:
        """Capture a frame as an RGB numpy array."""

    def _close(self) -> None:
        """Release backend resources."""


class DRMKMSCaptureBackend(CaptureBackend):
    """Placeholder DRM/KMS capture backend (legacy, unused by runtime)."""

    name = "drm-kms"

    def __init__(self, frame_spec: FrameSpec, card_path: Optional[str] = None) -> None:
        super().__init__(frame_spec)
        self.card_path = card_path or os.environ.get(
            "NANOLEAF_DRM_CARD", "/dev/dri/card0"
        )
        self._mapped_buffer: Optional[memoryview] = None

    def _open(self) -> None:
        if not sys.platform.startswith("linux"):
            raise BackendUnavailableError("DRM/KMS capture is only supported on Linux.")
        if not os.path.exists(self.card_path):
            raise BackendUnavailableError(f"DRM device not found: {self.card_path}")
        self._mapped_buffer = self._try_initialize_drm_mapping()
        if self._mapped_buffer is None:
            raise BackendUnavailableError("No DRM Python binding is configured.")

    def _capture(self) -> np.ndarray:
        if self._mapped_buffer is None:
            raise CaptureBackendError("DRM framebuffer is not mapped.")
        source = np.frombuffer(self._mapped_buffer, dtype=np.uint8)
        expected_size = self.frame_spec.width * self.frame_spec.height * 4
        if source.size < expected_size:
            raise CaptureBackendError(
                "Mapped DRM framebuffer is smaller than expected."
            )
        source = source[:expected_size].reshape(
            self.frame_spec.height, self.frame_spec.width, 4
        )
        return source[:, :, 2::-1].copy()

    def _close(self) -> None:
        self._mapped_buffer = None

    def _try_initialize_drm_mapping(self) -> Optional[memoryview]:
        return None


class KWinDBusCaptureBackend(CaptureBackend):
    """Stubbed KWin D-Bus capture backend (legacy, unused by runtime)."""

    name = "kwin-dbus"

    def __init__(self, frame_spec: FrameSpec) -> None:
        super().__init__(frame_spec)
        self._frame: Optional[np.ndarray] = None

    def _open(self) -> None:
        self._frame = np.zeros(self.frame_spec.shape, dtype=self.frame_spec.dtype)

    def _capture(self) -> np.ndarray:
        if self._frame is None:
            raise CaptureBackendError("KWin D-Bus stub backend is not initialized.")
        return self._frame


class ScreenCapture:
    """
    Low-latency screen capture facade (legacy, unused by runtime).

    The runtime uses capture.factory.create_capture_backend() instead.
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        prefer_backend: Optional[str] = None,
        card_path: Optional[str] = None,
    ) -> None:
        self.frame_spec = FrameSpec(width=width, height=height)
        self.prefer_backend = prefer_backend
        self.card_path = card_path
        self.backend = self._select_backend()

    def capture(self) -> np.ndarray:
        try:
            return self.backend.capture()
        except CaptureBackendError:
            if self.backend.name == KWinDBusCaptureBackend.name:
                raise
            self.backend.close()
            self.backend = KWinDBusCaptureBackend(self.frame_spec)
            return self.backend.capture()

    def close(self) -> None:
        self.backend.close()

    def _select_backend(self) -> CaptureBackend:
        if self.prefer_backend == KWinDBusCaptureBackend.name:
            return KWinDBusCaptureBackend(self.frame_spec)
        drm_backend = DRMKMSCaptureBackend(self.frame_spec, card_path=self.card_path)
        try:
            drm_backend.open()
            return drm_backend
        except BackendUnavailableError:
            drm_backend.close()
            return KWinDBusCaptureBackend(self.frame_spec)
