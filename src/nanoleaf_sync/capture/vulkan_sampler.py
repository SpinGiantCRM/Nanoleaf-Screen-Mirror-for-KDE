from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from nanoleaf_sync.capture.drm_zone_sampling import sample_zone_rects_from_dma_buf

_log = logging.getLogger(__name__)

_vulkan_last_error = ""
_vulkan_session: dict[str, Any] | None = None


def _vulkan_available() -> bool:
    global _vulkan_last_error
    env = os.environ.get("NANOLEAF_VULKAN_FORCE_AVAILABLE", "").strip().lower()
    if env in {"1", "true", "yes"}:
        return True
    import ctypes
    import ctypes.util

    lib = ctypes.util.find_library("vulkan")
    if not lib:
        _vulkan_last_error = "libvulkan_not_found"
        return False
    try:
        ctypes.CDLL(lib)
        return True
    except OSError as exc:
        _vulkan_last_error = f"{type(exc).__name__}: {exc}"
        return False


def _vulkan_import_dma_buf_image(
    *,
    fd: int,
    width: int,
    height: int,
    pixel_format: str,
    pitch_bytes: int = 0,
    fourcc: int = 0,
    modifier: int = 0,
    mapped_size: int = 0,
    card_path: str = "",
    cpu_sampler: Any | None = None,
) -> bool:
    global _vulkan_session, _vulkan_last_error
    if fd < 0:
        _vulkan_last_error = "invalid_dma_buf_fd"
        return False
    if not _vulkan_available():
        return False
    _vulkan_session = {
        "fd": int(fd),
        "width": int(width),
        "height": int(height),
        "pixel_format": str(pixel_format),
        "pitch_bytes": int(pitch_bytes),
        "fourcc": int(fourcc),
        "modifier": int(modifier),
        "mapped_size": int(mapped_size),
        "card_path": str(card_path),
        "cpu_sampler": cpu_sampler,
    }
    return True


def _vulkan_dispatch_zone_sampler(
    *, rects: Sequence[tuple[int, int, int, int]], width: int, height: int
) -> np.ndarray:
    global _vulkan_last_error
    if _vulkan_session is None:
        _vulkan_last_error = "vulkan_session_missing"
        raise RuntimeError(_vulkan_last_error)
    session = _vulkan_session
    mapped_size = int(session.get("mapped_size") or 0)
    if mapped_size <= 0:
        mapped_size = int(session.get("pitch_bytes") or 0) * int(session.get("height") or height)
    result = sample_zone_rects_from_dma_buf(
        dma_buf_fd=int(session["fd"]),
        mapped_size=mapped_size,
        width=int(session.get("width") or width),
        height=int(session.get("height") or height),
        pitch_bytes=int(session.get("pitch_bytes") or 0),
        fourcc=int(session.get("fourcc") or 0),
        modifier=int(session.get("modifier") or 0),
        card_path=str(session.get("card_path") or ""),
        rects=rects,
        cpu_sampler=session.get("cpu_sampler"),
    )
    if result.size == 0:
        _vulkan_last_error = "empty_zone_sample"
        raise RuntimeError(_vulkan_last_error)
    if result.dtype != np.uint8:
        return result
    if not np.any(result):
        _vulkan_last_error = "zero_zone_sample"
        raise RuntimeError(_vulkan_last_error)
    _vulkan_last_error = ""
    return result


def _vulkan_release() -> None:
    global _vulkan_session
    _vulkan_session = None


ZoneRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class VulkanSamplerStatus:
    available: bool
    reason: str


class VulkanZoneSampler:
    """DMA-BUF zone sampler with Vulkan session setup and mmap readback."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        dma_buf_fd: int,
        pixel_format: str = "rgba8",
        pitch_bytes: int = 0,
        fourcc: int = 0,
        modifier: int = 0,
        mapped_size: int = 0,
        card_path: str = "",
        cpu_sampler: Any | None = None,
    ) -> None:
        self._width = int(width)
        self._height = int(height)
        self._dma_buf_fd = int(dma_buf_fd)
        self._pixel_format = str(pixel_format)
        self._pitch_bytes = int(pitch_bytes)
        self._fourcc = int(fourcc)
        self._modifier = int(modifier)
        self._mapped_size = int(mapped_size)
        self._card_path = str(card_path)
        self._cpu_sampler = cpu_sampler
        self._initialized = False
        self._init_error = ""
        self._try_initialize()

    @staticmethod
    def probe() -> VulkanSamplerStatus:
        if os.environ.get("NANOLEAF_ENABLE_VULKAN_SAMPLER", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return VulkanSamplerStatus(available=False, reason="disabled_by_env")
        try:
            if _vulkan_available():
                return VulkanSamplerStatus(available=True, reason="vulkan_ready")
            return VulkanSamplerStatus(available=False, reason=_vulkan_last_error)
        except Exception as exc:
            return VulkanSamplerStatus(available=False, reason=f"{type(exc).__name__}: {exc}")

    @classmethod
    def try_create(
        cls,
        *,
        width: int,
        height: int,
        dma_buf_fd: int,
        pixel_format: str = "rgba8",
        pitch_bytes: int = 0,
        fourcc: int = 0,
        modifier: int = 0,
        mapped_size: int = 0,
        card_path: str = "",
        cpu_sampler: Any | None = None,
    ) -> VulkanZoneSampler | None:
        status = cls.probe()
        if not status.available:
            _log.debug("Vulkan zone sampler unavailable: %s", status.reason)
            return None
        if dma_buf_fd < 0:
            return None
        try:
            sampler = cls(
                width=width,
                height=height,
                dma_buf_fd=dma_buf_fd,
                pixel_format=pixel_format,
                pitch_bytes=pitch_bytes,
                fourcc=fourcc,
                modifier=modifier,
                mapped_size=mapped_size,
                card_path=card_path,
                cpu_sampler=cpu_sampler,
            )
        except Exception as exc:
            _log.debug("Vulkan zone sampler init failed: %s", exc, exc_info=True)
            return None
        if not sampler._initialized:
            return None
        return sampler

    def _try_initialize(self) -> None:
        if os.environ.get("NANOLEAF_ENABLE_VULKAN_SAMPLER", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            self._init_error = "disabled_by_env"
            return
        if self._dma_buf_fd < 0:
            self._init_error = "invalid_dma_buf_fd"
            return
        try:
            self._initialized = bool(
                _vulkan_import_dma_buf_image(
                    fd=self._dma_buf_fd,
                    width=self._width,
                    height=self._height,
                    pixel_format=self._pixel_format,
                    pitch_bytes=self._pitch_bytes,
                    fourcc=self._fourcc,
                    modifier=self._modifier,
                    mapped_size=self._mapped_size,
                    card_path=self._card_path,
                    cpu_sampler=self._cpu_sampler,
                )
            )
            if not self._initialized:
                self._init_error = _vulkan_last_error
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            self._initialized = False

    def sample_zone_rects(self, rects: Sequence[ZoneRect]) -> np.ndarray:
        if not self._initialized:
            raise RuntimeError(self._init_error or "vulkan_sampler_not_initialized")
        result = _vulkan_dispatch_zone_sampler(
            rects=[(int(x), int(y), int(w), int(h)) for x, y, w, h in rects],
            width=self._width,
            height=self._height,
        )
        if result.dtype != np.uint8:
            return np.asarray(result, dtype=np.float32)
        colors = np.asarray(result, dtype=np.uint8)
        if colors.ndim != 2 or colors.shape[1] != 3:
            raise RuntimeError("invalid_vulkan_zone_sampler_output")
        return colors

    def close(self) -> None:
        if not self._initialized:
            return
        try:
            _vulkan_release()
        except Exception:
            _log.debug("Vulkan sampler release failed", exc_info=True)
        finally:
            self._initialized = False

    def __enter__(self) -> VulkanZoneSampler:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        self.close()
        return False
