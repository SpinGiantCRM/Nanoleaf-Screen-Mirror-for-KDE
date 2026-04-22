from __future__ import annotations

import os
import inspect
from importlib import import_module
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
    _cached_drm_capture_impl: object | None = None
    _cached_probe_done: bool = False

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
        self._fallback = KWinDBusScreenshotCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )
        self._allow_fallback = bool(allow_fallback)
        self.last_capture_path: str = "drm-kms"

        self._hdr_defaults = HDRMetadata(
            transfer=str(hdr_transfer),
            primaries=str(hdr_primaries),
            max_nits=float(hdr_max_nits),
        )

        self._resize_index_cache: dict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._resize_index_cache_limit = 8
        self._drm_capture_impl = self._resolve_drm_capture_impl()

    @classmethod
    def _resolve_drm_capture_impl(cls):
        if cls._cached_probe_done:
            return cls._cached_drm_capture_impl
        cls._cached_drm_capture_impl = cls._probe_drm_capture_impl()
        cls._cached_probe_done = True
        return cls._cached_drm_capture_impl

    def capture(self) -> np.ndarray:
        try:
            if self._drm_capture_impl is None:
                raise KMSGrabError("DRM/KMS capture bindings are unavailable.")
            frame = self._capture_drm_rgb()
            self.last_capture_path = "drm-kms"
            return frame
        except KMSGrabError:
            if not self._allow_fallback:
                raise

            fallback_rgb = self._fallback.capture()
            self.last_capture_path = "kwin-dbus"
            return fallback_rgb

    def _capture_drm_rgb(self) -> np.ndarray:
        """Try available DRM capture bindings, otherwise raise KMSGrabError."""
        if self._drm_capture_impl is None:
            raise KMSGrabError(
                "DRM/KMS capture bindings are not available yet (expected _kmsgrab or kmsgrab module). "
                "Using KWin D-Bus fallback."
            )

        keyword_call = (
            f"{self._drm_capture_impl.__name__}(width=..., height=..., card_path=...)"
        )
        try:
            result = self._drm_capture_impl(
                width=self.params.width,
                height=self.params.height,
                card_path=self.params.card_path,
            )
            return self._convert_if_needed(result)
        except TypeError as keyword_error:
            if not self._supports_positional_call(self._drm_capture_impl):
                raise KMSGrabError(
                    "DRM capture callable rejected keyword invocation and does not "
                    f"support positional retry. Attempted signature: {keyword_call}. "
                    f"Original error: {keyword_error}"
                ) from keyword_error

            positional_call = (
                f"{self._drm_capture_impl.__name__}(width, height, card_path)"
            )
            try:
                result = self._drm_capture_impl(
                    self.params.width,
                    self.params.height,
                    self.params.card_path,
                )
                return self._convert_if_needed(result)
            except TypeError as positional_error:
                raise KMSGrabError(
                    "DRM capture callable rejected both invocation conventions. "
                    f"Attempted signatures: {keyword_call}, {positional_call}. "
                    f"Keyword error: {keyword_error}. Positional error: {positional_error}"
                ) from positional_error

    @staticmethod
    def _probe_drm_capture_impl():
        try:
            module = import_module("nanoleaf_sync.capture._kmsgrab")
            capture = getattr(module, "capture_dma_buf_rgb", None)
            if callable(capture):
                return capture
        except ImportError:
            pass

        try:
            module = import_module("kmsgrab")  # type: ignore
            capture = getattr(module, "capture", None)
            if callable(capture):
                return capture
        except ImportError:
            pass

        return None

    def _supports_positional_call(self, capture_impl: object) -> bool:
        """Return True when signature inspection indicates 3 positional args are accepted."""
        try:
            signature = inspect.signature(capture_impl)
        except (TypeError, ValueError):
            return True

        try:
            signature.bind_partial(1, 1, "/dev/dri/card0")
            return True
        except TypeError:
            return False

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

        target_h = int(self.params.height)
        target_w = int(self.params.width)
        if rgb.shape[0] != target_h or rgb.shape[1] != target_w:
            rgb = self._resize_to_target(frame=rgb, target_height=target_h, target_width=target_w)

        if (
            rgb.dtype == np.uint8
            and meta.transfer == "srgb"
            and meta.primaries == "bt709"
        ):
            return rgb

        return convert_frame_to_srgb8(rgb, metadata=meta)

    def _resize_to_target(
        self, *, frame: np.ndarray, target_height: int, target_width: int
    ) -> np.ndarray:
        """Resize frame to target capture dimensions if needed."""
        if frame.shape[0] == target_height and frame.shape[1] == target_width:
            return frame

        cache_key = (
            int(frame.shape[0]),
            int(frame.shape[1]),
            int(target_height),
            int(target_width),
        )
        cached = self._resize_index_cache.get(cache_key)
        if cached is None:
            y_idx = np.linspace(0, frame.shape[0] - 1, target_height).astype(np.intp)
            x_idx = np.linspace(0, frame.shape[1] - 1, target_width).astype(np.intp)
            self._resize_index_cache[cache_key] = (y_idx, x_idx)
            if len(self._resize_index_cache) > self._resize_index_cache_limit:
                self._resize_index_cache.pop(next(iter(self._resize_index_cache)))
        else:
            y_idx, x_idx = cached
        return frame[y_idx[:, None], x_idx[None, :], :]


def reset_cached_drm_probe() -> None:
    KMSGrabCapture._cached_drm_capture_impl = None
    KMSGrabCapture._cached_probe_done = False
