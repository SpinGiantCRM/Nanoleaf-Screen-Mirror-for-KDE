from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.color.hdr import HDRMetadata, convert_frame_to_srgb8


class KMSGrabError(RuntimeError):
    """Raised when DRM/KMS capture fails."""


@dataclass(frozen=True)
class KMSGrabParams:
    width: int
    height: int
    # Optional: allow overriding card device node.
    card_path: str = "/dev/dri/card0"


class KMSGrabCapture:
    """
    Low-latency DRM/KMS capture (kmsgrab-style) with KWin D-Bus fallback.

    Important:
    - Real DRM/KMS + DMA-BUF zero-copy capture requires platform-specific
      bindings (Python DRM wrappers or a small C/C++ extension).
    - Because the exact Python bindings available in your environment are
      unknown, this module provides a clean abstraction layer and a robust
      fallback to the stubbed KWin D-Bus screenshot capture.

    Interface:
    - `capture()` returns a numpy RGB array shaped (H, W, 3), dtype uint8.
    - The DRM/KMS path is implemented as a placeholder that can be replaced
      once you decide on a concrete libdrm/DMA-BUF binding strategy.
    """

    name = "kmsgrab"

    def __init__(
        self,
        width: int,
        height: int,
        card_path: Optional[str] = None,
        *,
        hdr_max_nits: float = 1000.0,
        hdr_transfer: str = "srgb",
        hdr_primaries: str = "bt709",
        allow_fallback: bool = True,
    ) -> None:
        self.params = KMSGrabParams(
            width=width,
            height=height,
            card_path=card_path
            or os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0"),
        )
        self._fallback = KWinDBusScreenshotCapture(width=width, height=height)
        self._allow_fallback = bool(allow_fallback)
        # Debug: records which path produced the most recent frame.
        # - "drm-kms" when the DRM binding hook returned pixels
        # - "kwin-dbus" when we fell back (or when DRM binding is missing)
        self.last_capture_path: str = "drm-kms"

        # Defaults used when the DRM/KMS binding returns pixels but no HDR metadata.
        self._hdr_defaults = HDRMetadata(
            transfer=str(hdr_transfer),
            primaries=str(hdr_primaries),
            max_nits=float(hdr_max_nits),
        )

        # Reusable black frame to avoid allocations on error.
        self._black = np.zeros(
            (self.params.height, self.params.width, 3), dtype=np.uint8
        )
        # For HDR transforms we only need zone-level color estimates.
        # Downsample before conversion to cap conversion cost on large frames.
        self._max_hdr_conversion_dim = 640

    def capture(self) -> np.ndarray:
        """
        Capture and return RGB pixels.

        Strategy:
        1. Try DRM/KMS capture via DMA-BUF / mapped framebuffer bytes.
        2. On any failure (binding missing, mapping unsupported, runtime error),
           fall back to KWin D-Bus capture.
        """

        try:
            frame = self._capture_drm_rgb()
            self.last_capture_path = "drm-kms"
            return frame
        except KMSGrabError:
            if not self._allow_fallback:
                raise

            # Even in fallback mode, run through the HDR->sRGB conversion
            # so the output contract stays consistent.
            fallback_rgb = self._fallback.capture()
            self.last_capture_path = "kwin-dbus"
            return self._convert_if_needed(fallback_rgb)

    def _capture_drm_rgb(self) -> np.ndarray:
        """
        DRM/KMS capture placeholder.

        What a future zero-copy implementation should do:
        - Enumerate DRM resources (connectors/CRTCs/planes)
        - Locate the active CRTC and its framebuffer
        - Export/import buffer via DMA-BUF
        - Map/attach the buffer and expose bytes as a numpy view
        - Convert from native pixel format (often XRGB/BGRX) to RGB

        Minimal-copy approach:
        - Use `numpy.frombuffer(mapped_bytes, dtype=np.uint8)` to wrap the memory
          without copying.
        - Use `reshape(H, W, 4)` for 4-channel formats.
        - Convert channel order into an RGB result.
          (This typically requires one materialization step unless you can
          provide an RGB view directly.)
        """

        # Attempt optional bindings provided by you later.
        #
        # The intent is:
        # - You (or another implementation) can supply a module that performs
        #   the actual libdrm + DMA-BUF / framebuffer mapping.
        # - That backend should return an RGB uint8 numpy array shaped (H, W, 3),
        #   ideally backed by a zero-copy bytes/memory view.
        #
        # Examples of acceptable backend module interfaces:
        # - `from ._kmsgrab import capture_dma_buf_rgb; return capture_dma_buf_rgb(...)`
        # - `import kmsgrab; kmsgrab.capture(width, height, card_path) -> np.ndarray`
        #
        # Because those bindings are not part of this scaffold, we fail
        # gracefully to the KWin fallback below.

        # 1) Proposed internal extension module (placeholder)
        try:
            from nanoleaf_sync.capture._kmsgrab import capture_dma_buf_rgb  # type: ignore

            result = capture_dma_buf_rgb(
                width=self.params.width,
                height=self.params.height,
                card_path=self.params.card_path,
            )
            return self._convert_if_needed(result)
        except ModuleNotFoundError:
            pass

        # 2) Generic external module hook (placeholder)
        try:
            import kmsgrab  # type: ignore

            result = kmsgrab.capture(
                width=self.params.width,
                height=self.params.height,
                card_path=self.params.card_path,
            )
            return self._convert_if_needed(result)
        except ModuleNotFoundError:
            pass

        raise KMSGrabError(
            "DRM/KMS capture bindings are not available yet (expected _kmsgrab or kmsgrab module). "
            "Using KWin D-Bus fallback."
        )

    def _convert_if_needed(self, result: object) -> np.ndarray:
        """
        Accept several possible return formats from future DRM bindings:
        - numpy.ndarray (already sRGB uint8 RGB)
        - (numpy.ndarray, metadata) where metadata includes HDR transfer/primaries
          and max_nits
        """

        if isinstance(result, tuple) and len(result) == 2:
            rgb, metadata = result
        else:
            rgb, metadata = result, self._hdr_defaults

        meta = HDRMetadata.from_any(metadata)

        if not isinstance(rgb, np.ndarray):
            raise TypeError(
                "DRM capture must return a numpy.ndarray (or (ndarray, metadata))."
            )

        # If we're already uint8 sRGB, this conversion is cheap but still costs
        # computation; we avoid it by checking the dtype first.
        if (
            rgb.dtype == np.uint8
            and meta.transfer == "srgb"
            and meta.primaries == "bt709"
        ):
            return rgb

        rgb_for_conversion = self._downsample_for_hdr_conversion(rgb)
        return convert_frame_to_srgb8(rgb_for_conversion, metadata=meta)

    def _downsample_for_hdr_conversion(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        max_dim = int(self._max_hdr_conversion_dim)
        if max(h, w) <= max_dim:
            return rgb

        scale = max(h / max_dim, w / max_dim)
        step = max(1, int(np.ceil(scale)))
        return rgb[::step, ::step, :]
