from __future__ import annotations

import os
import inspect
import logging
from importlib import import_module
from dataclasses import dataclass
from typing import Optional

import numpy as np

from nanoleaf_sync.capture._utils import _resize_to_target
from nanoleaf_sync.capture._drm_zone_sampler import DRMZoneSampler
from nanoleaf_sync.capture.errors import KMSGrabError
from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.color.hdr import HDRMetadata, analyze_hdr_path, convert_frame_to_srgb8

_log = logging.getLogger(__name__)


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
            card_path=card_path or os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0"),
        )
        self._fallback = KWinDBusScreenshotCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )
        self._allow_fallback = bool(allow_fallback)
        self.last_capture_path: str | None = "drm-kms"
        self.last_hdr_diagnostics: dict[str, object] = {}

        self._hdr_defaults = HDRMetadata(
            transfer=hdr_transfer
            if hdr_transfer in ("srgb", "pq", "hlg", "linear", "unknown")
            else "srgb",  # type: ignore[arg-type]
            primaries=hdr_primaries if hdr_primaries in ("bt709", "bt2020", "unknown") else "bt709",  # type: ignore[arg-type]
            max_nits=float(hdr_max_nits),
        )

        self._resize_index_cache: dict[
            tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]
        ] = {}
        self._resize_index_cache_limit = 8
        self._drm_capture_impl = self._resolve_drm_capture_impl()
        self._drm_zone_sampler: DRMZoneSampler | None = None
        if self._drm_capture_impl is None:
            try:
                self._drm_zone_sampler = DRMZoneSampler(
                    card_path=self.params.card_path,
                )
                _log.debug(
                    "kmsgrab: DRMZoneSampler initialised on %s (%dx%d)",
                    self.params.card_path,
                    self._drm_zone_sampler.width,
                    self._drm_zone_sampler.height,
                )
            except KMSGrabError:
                _log.debug(
                    "kmsgrab: DRMZoneSampler unavailable on %s; zone-patch capture disabled",
                    self.params.card_path,
                )

    def close(self) -> None:
        """Release D-Bus event-loop resources and DRM zone sampler."""
        if self._drm_zone_sampler is not None:
            try:
                self._drm_zone_sampler.close()
            except Exception:
                _log.debug("Failed to close DRM zone sampler", exc_info=True)
            self._drm_zone_sampler = None
        if hasattr(self._fallback, "close"):
            self._fallback.close()

    @classmethod
    def _resolve_drm_capture_impl(cls):
        if cls._cached_probe_done:
            return cls._cached_drm_capture_impl
        cls._cached_drm_capture_impl = cls._probe_drm_capture_impl()
        cls._cached_probe_done = True
        return cls._cached_drm_capture_impl

    def capture(
        self,
        zone_centers: list[tuple[int, int]] | None = None,
    ) -> np.ndarray:
        if (
            self._drm_zone_sampler is not None
            and zone_centers is not None
            and len(zone_centers) > 0
        ):
            try:
                patches = self._drm_zone_sampler.capture_zone_patches(
                    zone_centers,
                )
                self.last_capture_path = "drm-zone-patches"
                return patches
            except KMSGrabError:
                if not self._allow_fallback:
                    raise
                _log.warning(
                    "kmsgrab: DRM zone-patch capture failed; falling back to full-frame capture"
                )
        try:
            if self._drm_capture_impl is None:
                raise KMSGrabError("DRM/KMS capture bindings are unavailable.")
            frame = self._capture_drm_rgb()
            self.last_capture_path = "drm-kms"
            return frame
        except KMSGrabError:
            if not self._allow_fallback:
                raise

            _log.warning(
                "kmsgrab: DRM/KMS capture failed; falling back to kwin-dbus. "
                "If you explicitly selected kmsgrab, verify /dev/dri/card0 permissions "
                "and that the _kmsgrab or kmsgrab Python module is installed."
            )
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

        keyword_call = f"{self._drm_capture_impl.__name__}(width=..., height=..., card_path=...)"
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

            positional_call = f"{self._drm_capture_impl.__name__}(width, height, card_path)"
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
            module = import_module("kmsgrab")
            capture = getattr(module, "capture", None)
            if callable(capture):
                return capture
        except ImportError:
            pass

        return None

    def _supports_positional_call(self, capture_impl: object) -> bool:
        """Return True when signature inspection indicates 3 positional args are accepted."""
        try:
            signature = inspect.signature(capture_impl)  # type: ignore[arg-type]
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
            metadata_source = "backend metadata"
        else:
            rgb, metadata = result, self._hdr_defaults
            metadata_source = "user preset"

        meta = HDRMetadata.from_any(metadata)

        if not isinstance(rgb, np.ndarray):
            raise TypeError("DRM capture must return a numpy.ndarray (or (ndarray, metadata)).")

        target_h = int(self.params.height)
        target_w = int(self.params.width)
        if rgb.shape[0] != target_h or rgb.shape[1] != target_w:
            rgb = _resize_to_target(
                frame=rgb,
                target_height=target_h,
                target_width=target_w,
                index_cache=self._resize_index_cache,
                index_cache_limit=self._resize_index_cache_limit,
            )

        if rgb.dtype == np.uint8 and meta.transfer == "srgb" and meta.primaries == "bt709":
            self.last_hdr_diagnostics = {
                **analyze_hdr_path(
                    rgb,
                    metadata={
                        "transfer": "srgb",
                        "primaries": "bt709",
                        "max_nits": meta.max_nits,
                        "source": metadata_source,
                    },
                ),
                "hdr_max_nits": float(meta.max_nits),
            }
            return rgb

        self.last_hdr_diagnostics = {
            **analyze_hdr_path(
                rgb,
                metadata={
                    "transfer": meta.transfer,
                    "primaries": meta.primaries,
                    "max_nits": meta.max_nits,
                    "source": metadata_source,
                },
            ),
            "hdr_max_nits": float(meta.max_nits),
        }
        return convert_frame_to_srgb8(rgb, metadata=meta)

    def _resize_to_target(
        self, *, frame: np.ndarray, target_height: int, target_width: int
    ) -> np.ndarray:
        """Resize frame to target capture dimensions if needed."""
        return _resize_to_target(
            frame=frame,
            target_height=target_height,
            target_width=target_width,
            index_cache=self._resize_index_cache,
            index_cache_limit=self._resize_index_cache_limit,
        )


def reset_cached_drm_probe() -> None:
    KMSGrabCapture._cached_drm_capture_impl = None
    KMSGrabCapture._cached_probe_done = False
