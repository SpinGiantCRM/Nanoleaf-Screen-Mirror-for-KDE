from __future__ import annotations

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
    """
    Placeholder DRM/KMS capture backend.

    This class models a kmsgrab-style flow:
    - select a DRM device and plane/CRTC source
    - map the framebuffer or import a dma-buf
    - expose the frame as a numpy view with as little copying as possible

    The actual binding is intentionally abstract because Python DRM access varies
    widely by environment and the final choice of libdrm wrapper is project-specific.
    """

    name = "drm-kms"

    def __init__(self, frame_spec: FrameSpec, card_path: Optional[str] = None) -> None:
        super().__init__(frame_spec)
        self.card_path = card_path or os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0")
        self._mapped_buffer: Optional[memoryview] = None

    def _open(self) -> None:
        if not sys.platform.startswith("linux"):
            raise BackendUnavailableError("DRM/KMS capture is only supported on Linux.")

        if not os.path.exists(self.card_path):
            raise BackendUnavailableError(f"DRM device not found: {self.card_path}")

        self._mapped_buffer = self._try_initialize_drm_mapping()

        if self._mapped_buffer is None:
            raise BackendUnavailableError(
                "No DRM Python binding is configured. Provide a libdrm-backed mapping "
                "implementation for zero-copy framebuffer access."
            )

    def _capture(self) -> np.ndarray:
        if self._mapped_buffer is None:
            raise CaptureBackendError("DRM framebuffer is not mapped.")

        # Expected source layout is XRGB8888/BGRA-like, which is common for KMS.
        # `frombuffer` avoids an extra copy while wrapping the mapped memory.
        source = np.frombuffer(self._mapped_buffer, dtype=np.uint8)
        expected_size = self.frame_spec.width * self.frame_spec.height * 4
        if source.size < expected_size:
            raise CaptureBackendError("Mapped DRM framebuffer is smaller than expected.")

        source = source[:expected_size].reshape(self.frame_spec.height, self.frame_spec.width, 4)

        # Channel reordering to RGB requires one materialization step to produce a
        # compact, contiguous RGB array for downstream processing.
        return source[:, :, 2::-1].copy()

    def _close(self) -> None:
        self._mapped_buffer = None

    def _try_initialize_drm_mapping(self) -> Optional[memoryview]:
        """
        Hook point for a future libdrm-backed implementation.

        A real implementation should:
        - enumerate connectors/CRTCs/planes
        - acquire the active framebuffer handle
        - map or import the buffer with minimal copies
        - return a memoryview over raw bytes
        """

        return None


class KWinDBusCaptureBackend(CaptureBackend):
    """
    Stubbed KWin D-Bus capture backend.

    This backend keeps the interface working while the actual KWin screenshot
    integration is implemented. It returns a reusable black RGB frame so callers
    can exercise the full pipeline without hardware-specific capture support.
    """

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
    Low-latency screen capture facade with backend fallback.

    Backend order:
    1. DRM/KMS framebuffer capture
    2. KWin D-Bus screenshot fallback (stubbed)
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
        """
        Capture and return an RGB frame as a numpy array.

        On backend failure, the class attempts a one-time fallback to the KWin
        D-Bus stub so downstream modules can continue operating.
        """

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

