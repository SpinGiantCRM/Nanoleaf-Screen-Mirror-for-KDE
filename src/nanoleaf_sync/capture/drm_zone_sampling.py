"""Shared DMA-BUF / mmap zone-rectangle sampling for DRM and Vulkan paths."""

from __future__ import annotations

import ctypes
import mmap
from collections.abc import Sequence
from typing import Any

import numpy as np

from nanoleaf_sync.capture.drm_vendor import detect_drm_vendor, pixel_byte_offset
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

ZoneRect = tuple[int, int, int, int]

_FOURCC_NV_AB4H = 0x48344241
_10BIT_FOURCCS = frozenset({0x30334241, 0x30334258, 0x30335241, 0x30335258})
_FP16_FOURCCS = frozenset({_FOURCC_NV_AB4H})
_RGB_ORDER_FOURCCS = frozenset({0x34324258, 0x34324241, 0x30334258, 0x30334241, _FOURCC_NV_AB4H})


def _decode_fp16_half(value: int) -> float:
    exp = (value >> 10) & 0x1F
    mant = value & 0x3FF
    if exp == 0:
        return mant * (1.0 / 16384.0 / 1024.0)
    if exp == 31:
        return float("inf") if mant == 0 else float("nan")
    return (1.0 + mant / 1024.0) * (2.0 ** (exp - 15))


def _decode_10bit_pixel(word: int, *, rgb_order: bool) -> tuple[float, float, float]:
    if rgb_order:
        r10 = word & 0x3FF
        g10 = (word >> 10) & 0x3FF
        b10 = (word >> 20) & 0x3FF
    else:
        b10 = word & 0x3FF
        g10 = (word >> 10) & 0x3FF
        r10 = (word >> 20) & 0x3FF
    return float(r10), float(g10), float(b10)


def sample_zone_rects_from_dma_buf(
    *,
    dma_buf_fd: int,
    mapped_size: int,
    width: int,
    height: int,
    pitch_bytes: int,
    fourcc: int,
    modifier: int,
    card_path: str,
    rects: Sequence[ZoneRect],
    cpu_sampler: Any | None = None,
) -> np.ndarray:
    if cpu_sampler is not None and hasattr(cpu_sampler, "capture_zone_rects"):
        return np.asarray(cpu_sampler.capture_zone_rects(list(rects)), dtype=np.uint8)

    if dma_buf_fd < 0 or mapped_size <= 0 or not rects:
        return np.zeros((len(rects), 3), dtype=np.uint8)

    is_fp16 = fourcc in _FP16_FOURCCS
    is_10bit = fourcc in _10BIT_FOURCCS
    rgb_order = fourcc in _RGB_ORDER_FOURCCS
    vendor = detect_drm_vendor(card_path)
    bpp = 8 if is_fp16 else 4
    if is_10bit or is_fp16:
        out = np.zeros((len(rects), 3), dtype=np.float32)
    else:
        out = np.zeros((len(rects), 3), dtype=np.uint8)

    with mmap.mmap(dma_buf_fd, mapped_size, mmap.MAP_SHARED, mmap.PROT_READ) as mm:
        buf = (ctypes.c_uint8 * mapped_size).from_buffer(mm)
        for i, (x, y, w, h) in enumerate(rects):
            x0 = max(0, int(x))
            y0 = max(0, int(y))
            x1 = min(int(width), x0 + max(1, int(w)))
            y1 = min(int(height), y0 + max(1, int(h)))
            n_pixels = 0
            sum_r = 0.0
            sum_g = 0.0
            sum_b = 0.0
            sum_linear = np.zeros(3, dtype=np.float64)
            for py in range(y0, y1):
                for px in range(x0, x1):
                    pixel_base = pixel_byte_offset(
                        px=px,
                        py=py,
                        pitch_bytes=pitch_bytes,
                        bpp=bpp,
                        frame_width=width,
                        modifier=modifier,
                        vendor=vendor,
                    )
                    if is_fp16:
                        word1 = int(buf[pixel_base + 2]) | (int(buf[pixel_base + 3]) << 8)
                        word2 = int(buf[pixel_base + 4]) | (int(buf[pixel_base + 5]) << 8)
                        word3 = int(buf[pixel_base + 6]) | (int(buf[pixel_base + 7]) << 8)
                        sum_r += _decode_fp16_half(word1)
                        sum_g += _decode_fp16_half(word2)
                        sum_b += _decode_fp16_half(word3)
                    elif is_10bit:
                        word = (
                            int(buf[pixel_base])
                            | (int(buf[pixel_base + 1]) << 8)
                            | (int(buf[pixel_base + 2]) << 16)
                            | (int(buf[pixel_base + 3]) << 24)
                        )
                        r10, g10, b10 = _decode_10bit_pixel(word, rgb_order=rgb_order)
                        sum_r += r10
                        sum_g += g10
                        sum_b += b10
                    else:
                        if rgb_order:
                            rgb_u8 = np.array(
                                [buf[pixel_base], buf[pixel_base + 1], buf[pixel_base + 2]],
                                dtype=np.uint8,
                            )
                        else:
                            rgb_u8 = np.array(
                                [buf[pixel_base + 2], buf[pixel_base + 1], buf[pixel_base]],
                                dtype=np.uint8,
                            )
                        sum_linear += srgb_u8_to_linear01(rgb_u8[None, :])[0]
                    n_pixels += 1
            if n_pixels <= 0:
                continue
            if is_fp16 or is_10bit:
                if is_10bit:
                    out[i] = np.array([sum_r, sum_g, sum_b], dtype=np.float32) / (
                        float(n_pixels) * 1023.0
                    )
                else:
                    out[i] = np.array([sum_r, sum_g, sum_b], dtype=np.float32) / float(n_pixels)
            else:
                avg_linear = (sum_linear / float(n_pixels)).astype(np.float32, copy=False)
                out[i] = linear01_to_srgb_u8(avg_linear)
    return out
