from __future__ import annotations

import inspect
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import cast

import numpy as np

from nanoleaf_sync.capture._drm_zone_sampler import DRMZoneSampler
from nanoleaf_sync.capture._utils import _resize_to_target
from nanoleaf_sync.capture.errors import KMSGrabError
from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.capture.vulkan_sampler import VulkanZoneSampler
from nanoleaf_sync.color.capture_metadata import resolve_capture_metadata
from nanoleaf_sync.color.hdr import HDRMetadata, analyze_hdr_path, convert_frame_to_srgb8

_log = logging.getLogger(__name__)

_DRM_CARD_PATH_RE = re.compile(r"^/dev/dri/card\d+$")


def _wayland_session_active() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY", "").strip())


def validated_drm_card_path(raw: str | None = None) -> str:
    path = str(raw or os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0")).strip()
    if not _DRM_CARD_PATH_RE.match(path):
        raise KMSGrabError(f"Invalid DRM card path: {path!r}")
    return path


@dataclass(frozen=True)
class KMSGrabParams:
    width: int
    height: int
    card_path: str = "/dev/dri/card0"


class KMSGrabCapture:
    """DRM/KMS capture backend with optional KWin D-Bus fallback."""

    name = "kmsgrab"
    _cached_drm_capture_impl: Callable[..., np.ndarray] | None = None
    _cached_probe_done: bool = False

    def __init__(
        self,
        width: int,
        height: int,
        card_path: str | None = None,
        *,
        hdr_max_nits: float = 1000.0,
        hdr_transfer: str = "srgb",
        hdr_primaries: str = "bt709",
        allow_fallback: bool = True,
        drm_zone_patch_capture: bool = False,
    ) -> None:
        self.params = KMSGrabParams(
            width=width,
            height=height,
            card_path=validated_drm_card_path(card_path),
        )
        self._drm_zone_patch_capture = bool(drm_zone_patch_capture)
        self._fallback = KWinDBusScreenshotCapture(
            width=width,
            height=height,
            hdr_max_nits=hdr_max_nits,
            hdr_transfer=hdr_transfer,
            hdr_primaries=hdr_primaries,
        )
        self._allow_fallback = bool(allow_fallback)
        self._use_kwin_only = False
        self.last_capture_path: str | None = "drm-kms"
        self.last_hdr_diagnostics: dict[str, object] = {}
        self.last_drm_diagnostics: dict[str, object] = {
            "card_path": self.params.card_path,
            "width": width,
            "height": height,
        }

        self._hdr_defaults = HDRMetadata(
            transfer=hdr_transfer
            if hdr_transfer in ("srgb", "pq", "hlg", "linear", "gamma22", "unknown")
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
        self._vulkan_zone_sampler: VulkanZoneSampler | None = None
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
                # Enable zone-patch capture when no native C extension exists
                # but the Python DRMZoneSampler is available (NVIDIA FP16 path).
                self._drm_zone_patch_capture = True
                self._try_init_vulkan_sampler()
            except KMSGrabError:
                _log.debug(
                    "kmsgrab: DRMZoneSampler unavailable on %s; zone-patch capture disabled",
                    self.params.card_path,
                )

    def _try_init_vulkan_sampler(self) -> None:
        sampler = self._drm_zone_sampler
        if sampler is None:
            return
        fd = int(getattr(sampler, "dma_buf_fd", -1))
        if fd < 0:
            return
        self._vulkan_zone_sampler = VulkanZoneSampler.try_create(
            width=sampler.width,
            height=sampler.height,
            dma_buf_fd=fd,
        )

    def close(self) -> None:
        """Release D-Bus event-loop resources and DRM zone sampler."""
        if self._vulkan_zone_sampler is not None:
            try:
                self._vulkan_zone_sampler.close()
            except Exception:
                _log.debug("Failed to close Vulkan zone sampler", exc_info=True)
            self._vulkan_zone_sampler = None
        if self._drm_zone_sampler is not None:
            try:
                self._drm_zone_sampler.close()
            except Exception:
                _log.debug("Failed to close DRM zone sampler", exc_info=True)
            self._drm_zone_sampler = None
        if hasattr(self._fallback, "close"):
            self._fallback.close()

    @classmethod
    def _resolve_drm_capture_impl(cls) -> Callable[..., np.ndarray] | None:
        if cls._cached_probe_done:
            return cls._cached_drm_capture_impl
        cls._cached_drm_capture_impl = cls._probe_drm_capture_impl()
        cls._cached_probe_done = True
        return cls._cached_drm_capture_impl

    def capture(
        self,
        zone_centers: list[tuple[int, int]] | None = None,
        zone_rects: list[tuple[int, int, int, int]] | None = None,
    ) -> np.ndarray:
        if self._use_kwin_only:
            fallback_rgb = self._fallback.capture()
            self.last_capture_path = "kwin-dbus"
            return fallback_rgb

        if self._drm_zone_patch_capture and self._drm_zone_sampler is not None:
            display_rects = zone_rects
            if display_rects is None and zone_centers:
                display_rects = [(max(0, cx - 2), max(0, cy - 2), 5, 5) for cx, cy in zone_centers]
            # No explicit zones but sampler is available — capture a grid
            # covering the full frame so probe/fallback works.
            if not display_rects:
                w = self._drm_zone_sampler.width
                h = self._drm_zone_sampler.height
                step_x = max(1, w // 64)
                step_y = max(1, h // 36)
                display_rects = [
                    (x, y, step_x, step_y) for y in range(0, h, step_y) for x in range(0, w, step_x)
                ]
            if display_rects:
                try:
                    raw_patches: object
                    if self._vulkan_zone_sampler is not None:
                        raw_patches = self._vulkan_zone_sampler.sample_zone_rects(display_rects)
                        self.last_capture_path = "vulkan-zone-rects"
                    else:
                        raw_patches = self._drm_zone_sampler.capture_zone_rects(display_rects)
                        self.last_capture_path = "drm-zone-rects"
                    patches = self._convert_zone_result_if_needed(raw_patches)
                    if isinstance(patches, np.ndarray) and patches.ndim == 2:
                        self._record_drm_hdr_diagnostics(patches)
                    return patches
                except KMSGrabError:
                    if not self._allow_fallback:
                        raise
                    _log.warning(
                        "kmsgrab: DRM zone-rect capture failed; falling back to full-frame capture"
                    )
        try:
            if self._drm_capture_impl is None:
                raise KMSGrabError("DRM/KMS capture bindings are unavailable.")
            frame = self._capture_drm_rgb()
            self.last_capture_path = "drm-kms"
            self.last_drm_diagnostics = {
                "card_path": self.params.card_path,
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "capture_impl": getattr(self._drm_capture_impl, "__name__", "unknown"),
                "connector_id": getattr(self._drm_capture_impl, "connector_id", None),
                "connector_name": getattr(self._drm_capture_impl, "connector_name", None),
                "crtc_id": getattr(self._drm_capture_impl, "crtc_id", None),
                "framebuffer_id": getattr(self._drm_capture_impl, "framebuffer_id", None),
            }
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
            self._use_kwin_only = True
            return fallback_rgb

    def _capture_drm_rgb(self) -> np.ndarray:
        """Try available DRM capture bindings, otherwise raise KMSGrabError."""
        if self._drm_capture_impl is None:
            raise KMSGrabError(
                "DRM/KMS capture bindings are not available yet "
                "(expected _kmsgrab or kmsgrab module). "
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
    def _probe_drm_capture_impl() -> Callable[..., np.ndarray] | None:
        try:
            module = import_module("nanoleaf_sync.capture._kmsgrab")
            capture = getattr(module, "capture_dma_buf_rgb", None)
            if callable(capture):
                return cast(Callable[..., np.ndarray], capture)
        except ImportError:
            pass

        try:
            module = import_module("kmsgrab")
            capture = getattr(module, "capture", None)
            if callable(capture):
                return cast(Callable[..., np.ndarray], capture)
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

    def _convert_zone_result_if_needed(self, result: object) -> np.ndarray:
        if isinstance(result, tuple) and len(result) == 2:
            rgb, metadata = result
            if isinstance(rgb, np.ndarray) and rgb.ndim == 2 and rgb.shape[1] == 3:
                if rgb.dtype == np.uint8:
                    return rgb
                if rgb.dtype == np.float32 or rgb.dtype == np.float64:
                    expanded = rgb.reshape(1, rgb.shape[0], 3)
                    converted = self._convert_if_needed((expanded, metadata), skip_resize=True)
                    return converted.reshape(rgb.shape[0], 3)
        if isinstance(result, np.ndarray):
            return result
        return self._convert_if_needed(result)

    def _record_drm_hdr_diagnostics(self, rgb: np.ndarray) -> None:
        sampler = self._drm_zone_sampler
        if sampler is None or not bool(getattr(sampler, "is_10bit", False)):
            return
        capture_meta = sampler.capture_metadata
        if callable(capture_meta):
            capture_meta = capture_meta()
        if not isinstance(capture_meta, dict):
            return
        resolved = resolve_capture_metadata(
            backend_metadata=capture_meta,
            user_transfer=str(self._hdr_defaults.transfer),
            user_primaries=str(self._hdr_defaults.primaries),
            user_max_nits=float(self._hdr_defaults.max_nits),
        )
        meta = resolved.to_hdr_metadata()
        self.last_hdr_diagnostics = {
            **analyze_hdr_path(
                rgb.reshape(1, rgb.shape[0], 3),
                metadata={
                    "transfer": meta.transfer,
                    "primaries": meta.primaries,
                    "max_nits": meta.max_nits,
                    "bit_depth": capture_meta.get("bit_depth", 8),
                    "source": resolved.source,
                },
            ),
            "hdr_max_nits": float(meta.max_nits),
            "assumption": resolved.assumption,
            "skip_display_gamut_adaptation": resolved.skip_display_gamut_adaptation,
            "display_referred": True,
        }

    def _convert_if_needed(self, result: object, skip_resize: bool = False) -> np.ndarray:
        """Convert DRM output to uint8 sRGB; accepts ndarray or (ndarray, metadata)."""

        if isinstance(result, tuple) and len(result) == 2:
            rgb, metadata = result
            metadata_source = "backend metadata"
            meta = HDRMetadata.from_any(metadata)
            backend_metadata = {
                "transfer": meta.transfer,
                "primaries": meta.primaries,
                "max_nits": meta.max_nits,
                "source": metadata_source,
            }
        else:
            rgb = result
            metadata = HDRMetadata(
                transfer="srgb",
                primaries="bt709",
                max_nits=float(self._hdr_defaults.max_nits),
                skip_display_gamut_adaptation=True,
            )
            metadata_source = "backend display-referred"
            backend_metadata = {
                "transfer": metadata.transfer,
                "primaries": metadata.primaries,
                "max_nits": metadata.max_nits,
                "source": metadata_source,
                "display_referred": True,
            }

        meta = HDRMetadata.from_any(metadata)
        resolved = resolve_capture_metadata(
            backend_metadata=backend_metadata,
            user_transfer=str(self._hdr_defaults.transfer),
            user_primaries=str(self._hdr_defaults.primaries),
            user_max_nits=float(self._hdr_defaults.max_nits),
        )
        meta = resolved.to_hdr_metadata()

        bit_depth = None
        if isinstance(metadata, dict):
            raw_depth = metadata.get("bit_depth")
            if raw_depth is not None:
                bit_depth = int(raw_depth)

        if not isinstance(rgb, np.ndarray):
            raise TypeError("DRM capture must return a numpy.ndarray (or (ndarray, metadata)).")

        target_h = int(self.params.height)
        target_w = int(self.params.width)
        if not skip_resize and (rgb.shape[0] != target_h or rgb.shape[1] != target_w):
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
                        "source": resolved.source,
                    },
                ),
                "hdr_max_nits": float(meta.max_nits),
                "assumption": resolved.assumption,
                "skip_display_gamut_adaptation": resolved.skip_display_gamut_adaptation,
                "display_referred": resolved.source == "backend display-referred",
            }
            return cast(np.ndarray, rgb)

        convert_metadata = {
            "transfer": meta.transfer,
            "primaries": meta.primaries,
            "max_nits": meta.max_nits,
            "source": resolved.source,
        }
        if bit_depth is not None:
            convert_metadata["bit_depth"] = bit_depth

        self.last_hdr_diagnostics = {
            **analyze_hdr_path(
                rgb,
                metadata=convert_metadata,
            ),
            "hdr_max_nits": float(meta.max_nits),
            "assumption": resolved.assumption,
            "skip_display_gamut_adaptation": resolved.skip_display_gamut_adaptation,
            "display_referred": resolved.source == "backend display-referred",
        }
        if meta.transfer == "gamma22":
            self.last_hdr_diagnostics["display_referred"] = True
        return convert_frame_to_srgb8(
            rgb,
            metadata=convert_metadata,
        )

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
