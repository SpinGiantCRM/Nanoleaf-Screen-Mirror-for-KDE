from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from nanoleaf_sync.runtime.novel_features import vulkan_sampler_enabled

_log = logging.getLogger(__name__)

ZoneRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class VulkanSamplerStatus:
    available: bool
    reason: str


class VulkanZoneSampler:
    """Optional GPU zone sampler using DMA-BUF import. Falls back when unavailable."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        dma_buf_fd: int,
        pixel_format: str = "rgba8",
    ) -> None:
        self._width = int(width)
        self._height = int(height)
        self._dma_buf_fd = int(dma_buf_fd)
        self._pixel_format = str(pixel_format)
        self._initialized = False
        self._init_error = ""
        self._try_initialize()

    @staticmethod
    def probe() -> VulkanSamplerStatus:
        if not vulkan_sampler_enabled():
            return VulkanSamplerStatus(available=False, reason="disabled_by_env")
        try:
            from nanoleaf_sync.capture import _vulkan_loader as loader

            if loader.vulkan_available():
                return VulkanSamplerStatus(available=True, reason="vulkan_ready")
            return VulkanSamplerStatus(available=False, reason=loader.last_error())
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
            )
        except Exception as exc:
            _log.debug("Vulkan zone sampler init failed: %s", exc, exc_info=True)
            return None
        if not sampler._initialized:
            return None
        return sampler

    def _try_initialize(self) -> None:
        if not vulkan_sampler_enabled():
            self._init_error = "disabled_by_env"
            return
        if self._dma_buf_fd < 0:
            self._init_error = "invalid_dma_buf_fd"
            return
        try:
            from nanoleaf_sync.capture import _vulkan_loader as loader

            self._initialized = bool(
                loader.import_dma_buf_image(
                    fd=self._dma_buf_fd,
                    width=self._width,
                    height=self._height,
                    pixel_format=self._pixel_format,
                )
            )
            if not self._initialized:
                self._init_error = loader.last_error()
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            self._initialized = False

    def sample_zone_rects(self, rects: Sequence[ZoneRect]) -> np.ndarray:
        if not self._initialized:
            raise RuntimeError(self._init_error or "vulkan_sampler_not_initialized")
        from nanoleaf_sync.capture import _vulkan_loader as loader

        result = loader.dispatch_zone_sampler(
            rects=[(int(x), int(y), int(w), int(h)) for x, y, w, h in rects],
            width=self._width,
            height=self._height,
        )
        colors = np.asarray(result, dtype=np.uint8)
        if colors.ndim != 2 or colors.shape[1] != 3:
            raise RuntimeError("invalid_vulkan_zone_sampler_output")
        return colors

    def close(self) -> None:
        if not self._initialized:
            return
        try:
            from nanoleaf_sync.capture import _vulkan_loader as loader

            loader.release()
        except Exception:
            _log.debug("Vulkan sampler release failed", exc_info=True)
        finally:
            self._initialized = False

    def __enter__(self) -> VulkanZoneSampler:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        self.close()
        return False
