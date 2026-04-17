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
    card_path: str = "/dev/dri/card0"


class KMSGrabCapture:
    """DRM/KMS capture backend with optional KWin D-Bus fallback."""

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
        self.last_capture_path: str = "drm-kms"

        self._hdr_defaults = HDRMetadata(
            transfer=str(hdr_transfer),
            primaries=str(hdr_primaries),
            max_nits=float(hdr_max_nits),
        )

        # Downsample before HDR conversion to cap conversion cost on large frames.
        self._max_hdr_conversion_dim = 640

    def capture(self) -> np.ndarray:
        try:
            frame = self._capture_drm_rgb()
            self.last_capture_path = "drm-kms"
            return frame
        except KMSGrabError:
            if not self._allow_fallback:
                raise

            fallback_rgb = self._fallback.capture()
            self.last_capture_path = "kwin-dbus"
            return self._convert_if_needed(fallback_rgb)

    def _capture_drm_rgb(self) -> np.ndarray:
        """Try available DRM capture bindings, otherwise raise KMSGrabError."""
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
        """Convert DRM output to uint8 sRGB; accepts ndarray or (ndarray, metadata)."""

        if isinstance(result, tuple) and len(result) == 2:
            rgb, metadata = result
        else:
            rgb, metadata = result, self._hdr_defaults

        meta = HDRMetadata.from_any(metadata)

        if not isinstance(rgb, np.ndarray):
            raise TypeError(
                "DRM capture must return a numpy.ndarray (or (ndarray, metadata))."
            )

        if (
            rgb.dtype == np.uint8
            and meta.transfer == "srgb"
            and meta.primaries == "bt709"
        ):
            return rgb

        rgb_for_conversion = self._downsample_for_hdr_conversion(rgb)
        converted = convert_frame_to_srgb8(rgb_for_conversion, metadata=meta)
        return self._restore_converted_frame_shape(
            converted=converted,
            target_height=rgb.shape[0],
            target_width=rgb.shape[1],
        )

    def _downsample_for_hdr_conversion(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        max_dim = int(self._max_hdr_conversion_dim)
        if max(h, w) <= max_dim:
            return rgb

        scale = max(h / max_dim, w / max_dim)
        step = max(1, int(np.ceil(scale)))
        return rgb[::step, ::step, :]

    def _restore_converted_frame_shape(
        self, *, converted: np.ndarray, target_height: int, target_width: int
    ) -> np.ndarray:
        """Resize converted frame back to original capture dimensions if needed."""
        if converted.shape[0] == target_height and converted.shape[1] == target_width:
            return converted

        y_idx = np.linspace(0, converted.shape[0] - 1, target_height).astype(np.intp)
        x_idx = np.linspace(0, converted.shape[1] - 1, target_width).astype(np.intp)
        return converted[y_idx[:, None], x_idx[None, :], :]
