"""Direct DRM framebuffer zone sampler via ctypes ioctl/mmap.

This module implements a lightweight path that reads small pixel patches
directly from the display framebuffer without allocating a full frame
buffer copy.  When it can initialise successfully the runtime can sample
per-zone colours with a handful of ``read()`` + ``memcpy`` calls instead
of capturing and averaging a complete screen image.

All public errors are raised as :class:`KMSGrabError` so that callers in
``kmsgrab.py`` can fall through to the ``kwin-dbus`` backend transparently.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import logging
import math
import os
from typing import Any, Literal

import numpy as np

from nanoleaf_sync.capture._drm_helper_bridge import (
    DRMHelperMmapInfo,
    is_nvidia_x_tiled_modifier,
    mmap_helper_framebuffer,
    request_helper_mmap,
)
from nanoleaf_sync.capture.errors import KMSGrabError
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ioctl(2) number helpers  (matching the Linux kernel _IOC macros)
# ---------------------------------------------------------------------------

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS  #  8
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS  # 16
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS  # 30

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(direction: int, ioc_type: int, nr: int, size: int) -> int:
    """Replicate the kernel ``_IOC(dir, type, nr, size)`` macro."""
    return (
        (direction << _IOC_DIRSHIFT)
        | (ioc_type << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


# ---------------------------------------------------------------------------
# DRM ioctl type byte & ctypes structure definitions
# ---------------------------------------------------------------------------

_DRM_TYPE = ord("d")  # 0x64


class _DrmModeCardRes(ctypes.Structure):
    _fields_ = [
        ("fb_id_ptr", ctypes.c_uint64),
        ("crtc_id_ptr", ctypes.c_uint64),
        ("connector_id_ptr", ctypes.c_uint64),
        ("encoder_id_ptr", ctypes.c_uint64),
        ("count_fbs", ctypes.c_uint32),
        ("count_crtcs", ctypes.c_uint32),
        ("count_connectors", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
    ]


class _DrmModeModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),
        ("hdisplay", ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16),
        ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16),
        ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
    ]


class _DrmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("set_connectors_ptr", ctypes.c_uint64),
        ("count_connectors", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("fb_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("gamma_size", ctypes.c_uint32),
        ("mode_valid", ctypes.c_uint32),
        ("mode", _DrmModeModeInfo),
    ]


class _DrmModeGetConnector(ctypes.Structure):
    _fields_ = [
        ("encoders_ptr", ctypes.c_uint64),
        ("modes_ptr", ctypes.c_uint64),
        ("props_ptr", ctypes.c_uint64),
        ("prop_values_ptr", ctypes.c_uint64),
        ("count_modes", ctypes.c_uint32),
        ("count_props", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_uint32),
        ("mm_width", ctypes.c_uint32),
        ("mm_height", ctypes.c_uint32),
        ("subpixel", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class _DrmModeGetEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


class _DrmModeFbCmd2(ctypes.Structure):
    """``drm_mode_fb_cmd2`` — extended FB info including fourcc & modifiers."""

    _fields_ = [
        ("fb_id", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),  # fourcc code
        ("flags", ctypes.c_uint32),
        ("handles", ctypes.c_uint32 * 4),
        ("pitches", ctypes.c_uint32 * 4),
        ("offsets", ctypes.c_uint32 * 4),
        ("modifier", ctypes.c_uint64 * 4),
    ]


class _DrmModeMapDumb(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
        ("offset", ctypes.c_uint64),
    ]


class _DrmGemFlink(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
        ("name", ctypes.c_uint32),
    ]


class _DrmGemOpen(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),
        ("size", ctypes.c_uint64),
    ]


class _DrmPrimeHandle(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("fd", ctypes.c_int32),
    ]


class _DrmSetClientCap(ctypes.Structure):
    _fields_ = [
        ("capability", ctypes.c_uint64),
        ("value", ctypes.c_uint64),
    ]


class _DrmModeGetPlaneRes(ctypes.Structure):
    _fields_ = [
        ("plane_id_ptr", ctypes.c_uint64),
        ("count_planes", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class _DrmModeGetPlane(ctypes.Structure):
    _fields_ = [
        ("plane_id", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("fb_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("gamma_size", ctypes.c_uint32),
        ("count_format_types", ctypes.c_uint32),
        ("format_type_ptr", ctypes.c_uint64),
    ]


# ---------------------------------------------------------------------------
# IOCTL numbers  (computed once at import time so sizeof is stable)
# ---------------------------------------------------------------------------

DRM_IOCTL_MODE_GETRESOURCES = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xA0,
    ctypes.sizeof(_DrmModeCardRes),
)
DRM_IOCTL_MODE_GETCONNECTOR = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xA7,
    ctypes.sizeof(_DrmModeGetConnector),
)
DRM_IOCTL_MODE_GETENCODER = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xA6,
    ctypes.sizeof(_DrmModeGetEncoder),
)
DRM_IOCTL_MODE_GETCRTC = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xA1,
    ctypes.sizeof(_DrmModeCrtc),
)
DRM_IOCTL_MODE_GETFB2 = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xCE,
    ctypes.sizeof(_DrmModeFbCmd2),
)
DRM_IOCTL_MODE_MAP_DUMB = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xB3,
    ctypes.sizeof(_DrmModeMapDumb),
)
DRM_IOCTL_SET_CLIENT_CAP = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0x0D,
    ctypes.sizeof(_DrmSetClientCap),
)
DRM_IOCTL_MODE_GETPLANERESOURCES = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xB5,
    ctypes.sizeof(_DrmModeGetPlaneRes),
)
DRM_IOCTL_MODE_GETPLANE = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xB6,
    ctypes.sizeof(_DrmModeGetPlane),
)
DRM_IOCTL_GEM_FLINK = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xB9,
    ctypes.sizeof(_DrmGemFlink),
)
DRM_IOCTL_GEM_OPEN = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0xB7,
    ctypes.sizeof(_DrmGemOpen),
)
DRM_IOCTL_PRIME_HANDLE_TO_FD = _IOC(
    _IOC_READ | _IOC_WRITE,
    _DRM_TYPE,
    0x2D,
    ctypes.sizeof(_DrmPrimeHandle),
)

DRM_CLIENT_CAP_UNIVERSAL_PLANES = 2
_DRM_PRIME_CLOEXEC = 0x01

# Connection states  (drm_mode.h)
DRM_MODE_CONNECTED = 1

# Fourcc codes for the 32 bpp formats this module supports
_FOURCC_XR24 = 0x34325258  # X8 R8 G8 B8  (little-endian byte order: B, G, R, X)
_FOURCC_AR24 = 0x34325241  # A8 R8 G8 B8
_FOURCC_XB24 = 0x34324258  # X8 B8 G8 R8  (little-endian byte order: R, G, B, X)
_FOURCC_AB24 = 0x34324241  # A8 B8 G8 R8
_FOURCC_AB30 = 0x30334241  # A2 B10 G10 R10
_FOURCC_XB30 = 0x30334258  # X2 B10 G10 R10
_FOURCC_AR30 = 0x30335241  # A2 R10 G10 B10
_FOURCC_XR30 = 0x30335258  # X2 R10 G10 B10
_FOURCC_NV_AB4H = 0x48344241  # NVIDIA ABGR16_16_16_16_FLOAT (FP16)

_8BIT_FOURCCS = frozenset({_FOURCC_XR24, _FOURCC_AR24, _FOURCC_XB24, _FOURCC_AB24})
_10BIT_FOURCCS = frozenset({_FOURCC_AB30, _FOURCC_XB30, _FOURCC_AR30, _FOURCC_XR30})
_FP16_FOURCCS = frozenset({_FOURCC_NV_AB4H})
_SUPPORTED_FOURCCS = _8BIT_FOURCCS | _10BIT_FOURCCS | _FP16_FOURCCS
_RGB_ORDER_FOURCCS = frozenset(
    {_FOURCC_XB24, _FOURCC_AB24, _FOURCC_XB30, _FOURCC_AB30, _FOURCC_NV_AB4H}
)

_PATCH_RADIUS = 2
_NVIDIA_TILE_WIDTH = 16
_NVIDIA_TILE_HEIGHT = 128


def _nvidia_x_tiled_pixel_offset(px: int, py: int, frame_width: int, *, bpp: int = 4) -> int:
    tilex = _NVIDIA_TILE_WIDTH
    tiley = _NVIDIA_TILE_HEIGHT
    sno = (px // tilex) + (py // tiley) * (frame_width // tilex)
    ord_ = (px % tilex) + (py % tiley) * tilex
    return (sno * tilex * tiley + ord_) * bpp


def _fp16_linear_channel_to_u8(value: float) -> int:
    if not math.isfinite(value) or value < 0.0:
        return 0
    if value > 1.0:
        return 255
    return int(round(value * 255.0))


def _fp16_zone_to_uint8(avg_r: float, avg_g: float, avg_b: float) -> np.ndarray:
    return np.array(
        [
            _fp16_linear_channel_to_u8(avg_r),
            _fp16_linear_channel_to_u8(avg_g),
            _fp16_linear_channel_to_u8(avg_b),
        ],
        dtype=np.uint8,
    )


def _decode_fp16_half(value: int) -> float:
    exp = (value >> 10) & 0x1F
    mant = value & 0x3FF
    if exp == 0:
        return mant * (1.0 / 16384.0 / 1024.0)
    if exp == 31:
        return float("inf") if mant == 0 else float("nan")
    return (1.0 + mant / 1024.0) * (2.0 ** (exp - 15))


def _decode_10bit_pixel(word: int, *, rgb_order: bool) -> tuple[int, int, int]:
    if rgb_order:
        r10 = word & 0x3FF
        g10 = (word >> 10) & 0x3FF
        b10 = (word >> 20) & 0x3FF
    else:
        b10 = word & 0x3FF
        g10 = (word >> 10) & 0x3FF
        r10 = (word >> 20) & 0x3FF
    return r10, g10, b10


def _resolve_drm_primaries() -> str:
    try:
        from nanoleaf_sync.color.primaries import get_display_primaries_from_sysfs

        if get_display_primaries_from_sysfs() is not None:
            return "bt2020"
    except Exception:
        _log.debug("DRM primaries lookup failed", exc_info=True)
    return "bt2020"


class DRMZoneSampler:
    """Direct framebuffer zone-patch sampler via DRM ioctls and mmap.

    On success the sampler holds a read-only mmap of the current CRTC's
    framebuffer.  Callers use :meth:`capture_zone_patches` to extract
    per-zone averages without allocating an intermediate full-frame buffer.

    If *any* initialisation step fails a :class:`KMSGrabError` is raised so
    the ``kmsgrab`` caller can fall back to ``kwin-dbus``.
    """

    def __init__(self, card_path: str = "/dev/dri/card0") -> None:
        self._card_path: str = os.fspath(card_path)
        self._fd: int = -1
        self._mapped_ptr: int | None = None
        self._mapped_size: int = 0
        self._width: int = 0
        self._height: int = 0
        self._pitch_bytes: int = 0
        self._fourcc: int = 0
        self._is_10bit: bool = False
        self._is_fp16: bool = False
        self._rgb_order: bool = False
        self._dma_buf_fd: int = -1
        self._fd_cloned: bool = False
        self._r_byte: int = 2
        self._g_byte: int = 1
        self._b_byte: int = 0
        self._libc: Any = None
        self._crtc_id: int = 0
        self._fb_id: int = 0
        self._remount_count: int = 0
        self._helper_dma_mmap: bool = False
        self._modifier: int = 0
        self._nvidia_x_tiled: bool = False

        try:
            self._init()
        except Exception as exc:
            self.close()
            raise KMSGrabError(f"DRMZoneSampler init failed for {self._card_path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init(self) -> None:
        helper_info = request_helper_mmap(card_path=self._card_path, fb_id=0)
        if helper_info is not None:
            self._init_via_helper(helper_info)
            return
        # Helper failed for primary card; try secondary card (NVIDIA).
        alt_card = self._card_path.rstrip("0123456789") + "1"
        if alt_card != self._card_path:
            helper_info = request_helper_mmap(card_path=alt_card, fb_id=0)
            if helper_info is not None:
                self._card_path = alt_card
                self._init_via_helper(helper_info)
                return
        # No helper available — fall through to direct DRM open.
        if helper_info is not None and not helper_info.is_dma_buf:
            self._fd = int(helper_info.pass_fd)
            self._fd_cloned = True
        else:
            self._fd = os.open(self._card_path, os.O_RDONLY)
            self._fd_cloned = False
        if self._fd < 0:
            raise OSError(f"cannot open {self._card_path}")

        # Cache libc with correct signatures for mmap/munmap
        libc = ctypes.CDLL("libc.so.6")
        libc.mmap.restype = ctypes.c_void_p
        libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.munmap.restype = ctypes.c_int
        self._libc = libc

        # 1. Get resources (two-call pattern like libdrm)
        res1 = _DrmModeCardRes()
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETRESOURCES, res1)
        except OSError as exc:
            raise KMSGrabError(f"DRM_IOCTL_MODE_GETRESOURCES failed on {self._card_path}") from exc

        count_crtcs = int(res1.count_crtcs)
        count_connectors = int(res1.count_connectors)
        count_encoders = int(res1.count_encoders)
        count_fbs = int(res1.count_fbs)

        if count_crtcs <= 0:
            raise KMSGrabError("no CRTCs reported by DRM")

        # Second call with a buffer large enough for struct + all arrays.
        # Kernel writes arrays after the struct in order: fb_ids, crtc_ids,
        # connector_ids, encoder_ids.  The struct pointer fields must be
        # real user-space addresses pointing into the same buffer, otherwise
        # the kernel treats them as NULL and will not populate the arrays.
        struct_sz = ctypes.sizeof(_DrmModeCardRes)
        total_sz = struct_sz + (count_fbs + count_crtcs + count_connectors + count_encoders) * 4
        _buf = (ctypes.c_uint8 * total_sz)()
        ctypes.memmove(_buf, ctypes.addressof(res1), struct_sz)

        # Patch the pointer fields to point at the array regions within _buf.
        _buf_addr: int = ctypes.addressof(_buf)
        res = _DrmModeCardRes.from_buffer(_buf)
        _offset = struct_sz
        res.fb_id_ptr = _buf_addr + _offset
        _offset += count_fbs * 4
        res.crtc_id_ptr = _buf_addr + _offset
        _offset += count_crtcs * 4
        res.connector_id_ptr = _buf_addr + _offset
        _offset += count_connectors * 4
        res.encoder_id_ptr = _buf_addr + _offset

        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETRESOURCES, _buf)
        except OSError as exc:
            raise KMSGrabError(
                f"DRM_IOCTL_MODE_GETRESOURCES (phase 2) failed on {self._card_path}"
            ) from exc

        # 2. Walk CRTCs to find an active CRTC with a framebuffer
        crtc_id = self._find_active_crtc(
            buf=_buf,
            struct_sz=struct_sz,
            count_crtcs=count_crtcs,
            count_connectors=count_connectors,
            count_fbs=count_fbs,
        )

        # 3. Get CRTC state (framebuffer id + mode)
        crtc = _DrmModeCrtc()
        fb_id = 0
        if crtc_id != 0:
            crtc.crtc_id = crtc_id
            try:
                fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
            except OSError as exc:
                _log.debug("DRM_IOCTL_MODE_GETCRTC failed for CRTC %s: %s", crtc_id, exc)
            else:
                fb_id = int(crtc.fb_id)

        if fb_id == 0 or crtc_id == 0:
            plane_fb_id, plane_crtc_id = self._find_active_fb_via_planes()
            if plane_fb_id != 0:
                fb_id = plane_fb_id
                if plane_crtc_id != 0 and (crtc_id == 0 or int(crtc.crtc_id) != plane_crtc_id):
                    crtc = _DrmModeCrtc()
                    crtc.crtc_id = plane_crtc_id
                    try:
                        fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
                    except OSError as exc:
                        _log.debug(
                            "DRM_IOCTL_MODE_GETCRTC failed for plane CRTC %s: %s",
                            plane_crtc_id,
                            exc,
                        )
                if crtc_id == 0 and plane_crtc_id != 0:
                    crtc_id = plane_crtc_id

        if fb_id == 0:
            helper_info = request_helper_mmap(card_path=self._card_path, fb_id=0)
            if helper_info is not None:
                if helper_info.is_dma_buf:
                    self._init_via_helper(helper_info)
                    return
                if self._fd >= 0 and not self._fd_cloned:
                    with contextlib.suppress(OSError):
                        os.close(self._fd)
                self._fd = int(helper_info.pass_fd)
                self._fd_cloned = True
                plane_fb_id, plane_crtc_id = self._find_active_fb_via_planes()
                if plane_fb_id != 0:
                    fb_id = plane_fb_id
                    if plane_crtc_id != 0:
                        crtc_id = plane_crtc_id
                        crtc = _DrmModeCrtc()
                        crtc.crtc_id = plane_crtc_id
                        with contextlib.suppress(OSError):
                            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
            if fb_id == 0:
                raise KMSGrabError("no active framebuffer found via CRTC or planes")

        self._crtc_id = int(crtc_id) if crtc_id != 0 else int(crtc.crtc_id)
        self._fb_id = int(fb_id)
        self._attach_framebuffer(crtc=crtc, fb_id=int(fb_id))

    def _apply_helper_layout(self, info: DRMHelperMmapInfo) -> None:
        self._modifier = int(info.modifier)
        self._nvidia_x_tiled = is_nvidia_x_tiled_modifier(self._modifier)

    def _init_via_helper(self, info: DRMHelperMmapInfo) -> None:
        libc = ctypes.CDLL("libc.so.6")
        libc.mmap.restype = ctypes.c_void_p
        libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.munmap.restype = ctypes.c_int
        self._libc = libc
        self._fb_id = int(info.fb_id)
        self._fourcc = int(info.fourcc)
        self._pitch_bytes = int(info.pitch)
        self._apply_helper_format()
        self._apply_helper_layout(info)
        if info.is_dma_buf:
            self._helper_dma_mmap = True
            self._dma_buf_fd = int(info.pass_fd)
        else:
            self._fd = int(info.pass_fd)
            self._fd_cloned = True
        width = int(info.width)
        height = int(info.height)
        if width <= 0 or height <= 0:
            width, height = self._fb_dimensions(self._fb_id)
        if width <= 0 or height <= 0:
            usable = int(info.size) - int(info.offset)
            if int(info.pitch) > 0 and usable > 0:
                height = usable // int(info.pitch)
            if width <= 0 and int(info.pitch) >= 4:
                width = int(info.pitch) // 4
        if width <= 0 or height <= 0:
            raise KMSGrabError("invalid framebuffer dimensions from DRM helper")
        self._width = int(width)
        self._height = int(height)
        self._mapped_ptr, self._mapped_size = mmap_helper_framebuffer(info, libc)
        if self._mapped_ptr is None or self._mapped_ptr == 0:
            raise KMSGrabError("mmap of DRM helper framebuffer failed")

    def _apply_helper_format(self) -> None:
        if self._fourcc not in _SUPPORTED_FOURCCS:
            raise KMSGrabError(
                f"unsupported DRM fourcc 0x{self._fourcc:08X}; "
                "expected XR24/AR24/XB24/AB24 or XR30/AR30/XB30/AB30"
            )
        self._is_fp16 = self._fourcc in _FP16_FOURCCS
        self._is_10bit = self._fourcc in _10BIT_FOURCCS
        self._rgb_order = self._fourcc in _RGB_ORDER_FOURCCS
        if self._is_fp16:
            self._nvidia_x_tiled = True
        elif self._is_10bit:
            self._r_byte, self._g_byte, self._b_byte = 0, 1, 2
        else:
            if self._rgb_order:
                self._r_byte, self._g_byte, self._b_byte = 0, 1, 2
            else:
                self._b_byte, self._g_byte, self._r_byte = 0, 1, 2

    def _fb_dimensions(self, fb_id: int) -> tuple[int, int]:
        probe_fd = self._fd
        close_probe = False
        if probe_fd < 0:
            probe_fd = os.open(self._card_path, os.O_RDONLY)
            close_probe = True
        try:
            fb2 = _DrmModeFbCmd2()
            fb2.fb_id = int(fb_id)
            fcntl.ioctl(probe_fd, DRM_IOCTL_MODE_GETFB2, fb2)
            return int(fb2.width), int(fb2.height)
        except OSError:
            return 0, 0
        finally:
            if close_probe and probe_fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(probe_fd)

    def _apply_helper_mmap(self, info: DRMHelperMmapInfo) -> None:
        if self._libc is None:
            libc = ctypes.CDLL("libc.so.6")
            libc.mmap.restype = ctypes.c_void_p
            libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            libc.munmap.restype = ctypes.c_int
            self._libc = libc
        self._fourcc = int(info.fourcc)
        self._pitch_bytes = int(info.pitch)
        self._apply_helper_format()
        self._apply_helper_layout(info)
        self._fb_id = int(info.fb_id)
        if info.is_dma_buf:
            self._helper_dma_mmap = True
        elif not self._fd_cloned:
            self._fd = int(info.pass_fd)
            self._fd_cloned = True
        width = int(info.width) if int(info.width) > 0 else int(self._width)
        height = int(info.height) if int(info.height) > 0 else int(self._height)
        if width <= 0 or height <= 0:
            width, height = self._fb_dimensions(self._fb_id)
        if width <= 0 or height <= 0:
            width = int(self._width)
            height = int(self._height)
        if width <= 0 or height <= 0:
            usable = int(info.size) - int(info.offset)
            if int(info.pitch) > 0 and usable > 0:
                height = usable // int(info.pitch)
            if width <= 0 and int(info.pitch) >= 4:
                width = int(info.pitch) // 4
        if width <= 0 or height <= 0:
            raise KMSGrabError("invalid framebuffer dimensions from DRM helper")
        self._width = int(width)
        self._height = int(height)
        self._mapped_ptr, self._mapped_size = mmap_helper_framebuffer(info, self._libc)
        if info.is_dma_buf:
            self._dma_buf_fd = int(info.pass_fd)
        elif not self._fd_cloned:
            self._fd = int(info.pass_fd)
            self._fd_cloned = True
        elif int(info.pass_fd) != self._fd:
            with contextlib.suppress(OSError):
                os.close(int(info.pass_fd))

    def _unmap_framebuffer(self) -> None:
        if self._mapped_ptr is not None and self._mapped_ptr != 0 and self._mapped_size > 0:
            libc = self._libc
            if libc is None:
                libc = ctypes.CDLL("libc.so.6")
                libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                libc.munmap.restype = ctypes.c_int
            with contextlib.suppress(Exception):
                libc.munmap(
                    ctypes.c_void_p(self._mapped_ptr),
                    ctypes.c_size_t(self._mapped_size),
                )
            self._mapped_ptr = None
            self._mapped_size = 0
        if self._dma_buf_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._dma_buf_fd)
            self._dma_buf_fd = -1

    def _attach_framebuffer(self, *, crtc: _DrmModeCrtc, fb_id: int) -> None:
        fb2 = _DrmModeFbCmd2()
        fb2.fb_id = fb_id
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETFB2, fb2)
        except OSError as exc:
            raise KMSGrabError(f"DRM_IOCTL_MODE_GETFB2 failed for FB {fb_id}") from exc

        self._width = int(crtc.mode.hdisplay)
        self._height = int(crtc.mode.vdisplay)
        if self._width <= 0 or self._height <= 0:
            self._width = int(fb2.width)
            self._height = int(fb2.height)
        if self._width <= 0 or self._height <= 0:
            raise KMSGrabError(f"invalid framebuffer dimensions: {self._width}x{self._height}")

        self._fourcc = int(fb2.pixel_format)
        self._pitch_bytes = int(fb2.pitches[0])
        self._modifier = int(fb2.modifier[0])
        self._nvidia_x_tiled = is_nvidia_x_tiled_modifier(self._modifier)
        handle = int(fb2.handles[0])
        buff_offset = int(fb2.offsets[0])

        if self._fourcc not in _SUPPORTED_FOURCCS:
            raise KMSGrabError(
                f"unsupported DRM fourcc 0x{self._fourcc:08X}; "
                "expected XR24/AR24/XB24/AB24 or XR30/AR30/XB30/AB30"
            )

        self._is_10bit = self._fourcc in _10BIT_FOURCCS
        self._rgb_order = self._fourcc in _RGB_ORDER_FOURCCS
        if not self._is_10bit:
            if self._rgb_order:
                self._r_byte, self._g_byte, self._b_byte = 0, 1, 2
            else:
                self._b_byte, self._g_byte, self._r_byte = 0, 1, 2

        if handle == 0:
            helper_info = request_helper_mmap(card_path=self._card_path, fb_id=fb_id)
            if helper_info is not None:
                self._apply_helper_mmap(helper_info)
                return
            raise KMSGrabError(
                f"DRM framebuffer {fb_id} has zero GEM handle; DRM helper may be unavailable"
            )

        self._mmap_framebuffer_memory(handle=handle, fb_id=fb_id, buff_offset=buff_offset)

    def _mmap_framebuffer_memory(self, *, handle: int, fb_id: int, buff_offset: int) -> None:
        self._mapped_size = int(self._height) * int(self._pitch_bytes) + int(buff_offset)
        map_offset = self._map_dumb_offset(handle)
        if map_offset is not None:
            self._mapped_ptr = self._mmap_fd(
                fd=self._fd,
                size=self._mapped_size,
                offset=int(map_offset),
            )
            self._fb_id = int(fb_id)
            return

        dma_fd = self._prime_handle_to_fd(handle)
        if dma_fd is not None:
            self._dma_buf_fd = int(dma_fd)
            self._mapped_ptr = self._mmap_fd(
                fd=self._dma_buf_fd,
                size=self._mapped_size,
                offset=0,
            )
            self._fb_id = int(fb_id)
            return

        reopened = self._reopen_handle_via_flink(handle)
        if reopened is not None:
            map_offset = self._map_dumb_offset(reopened)
            if map_offset is not None:
                self._mapped_ptr = self._mmap_fd(
                    fd=self._fd,
                    size=self._mapped_size,
                    offset=int(map_offset),
                )
                self._fb_id = int(fb_id)
                return

        raise KMSGrabError(f"failed to mmap DRM framebuffer for handle {handle}")

    def _map_dumb_offset(self, handle: int) -> int | None:
        _map_dumb = _DrmModeMapDumb()
        _map_dumb.handle = int(handle)
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_MAP_DUMB, _map_dumb)
        except OSError as exc:
            _log.debug("DRM_IOCTL_MODE_MAP_DUMB failed for handle %s: %s", handle, exc)
            return None
        return int(_map_dumb.offset)

    def _prime_handle_to_fd(self, handle: int) -> int | None:
        prime = _DrmPrimeHandle()
        prime.handle = int(handle)
        prime.flags = _DRM_PRIME_CLOEXEC
        prime.fd = -1
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, prime)
        except OSError as exc:
            _log.debug("DRM_IOCTL_PRIME_HANDLE_TO_FD failed for handle %s: %s", handle, exc)
            return None
        if int(prime.fd) < 0:
            return None
        return int(prime.fd)

    def _reopen_handle_via_flink(self, handle: int) -> int | None:
        flink = _DrmGemFlink()
        flink.handle = int(handle)
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_GEM_FLINK, flink)
        except OSError as exc:
            _log.debug("DRM_IOCTL_GEM_FLINK failed for handle %s: %s", handle, exc)
            return None
        open_req = _DrmGemOpen()
        open_req.name = int(flink.name)
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_GEM_OPEN, open_req)
        except OSError as exc:
            _log.debug("DRM_IOCTL_GEM_OPEN failed for name %s: %s", flink.name, exc)
            return None
        return int(open_req.handle)

    def _maybe_reopen_drm_fd(self) -> bool:
        if self._helper_dma_mmap:
            helper_info = request_helper_mmap(
                card_path=self._card_path,
                fb_id=self._fb_id if self._fb_id > 0 else 0,
            )
            if helper_info is None:
                return False
            self._unmap_framebuffer()
            self._apply_helper_mmap(helper_info)
            return True
        helper_info = request_helper_mmap(
            card_path=self._card_path,
            fb_id=self._fb_id if self._fb_id > 0 else 0,
        )
        if helper_info is None or helper_info.is_dma_buf:
            return False
        if self._fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._fd)
        self._fd = int(helper_info.pass_fd)
        self._fd_cloned = True
        return True

    def _mmap_fd(self, *, fd: int, size: int, offset: int) -> int:
        PROT_READ = 0x01
        MAP_SHARED = 0x01
        MAP_FAILED_VALUE = ctypes.c_void_p(-1).value or -1

        _ptr = self._libc.mmap(
            None,
            ctypes.c_size_t(size),
            ctypes.c_int(PROT_READ),
            ctypes.c_int(MAP_SHARED),
            ctypes.c_int(fd),
            ctypes.c_long(offset),
        )
        _ptr_addr: int | None = _ptr.value if _ptr else None
        if _ptr_addr is None or _ptr_addr == MAP_FAILED_VALUE:
            raise KMSGrabError("mmap of DRM framebuffer failed")
        return int(_ptr_addr)

    def _capture_metadata(self) -> dict[str, object]:
        if self._is_fp16:
            bit_depth = 16
            transfer = "linear"
        elif self._is_10bit:
            bit_depth = 10
            transfer = "gamma22"
        else:
            bit_depth = 8
            transfer = "srgb"
        return {
            "fourcc": int(self._fourcc),
            "bit_depth": bit_depth,
            "primaries": _resolve_drm_primaries(),
            "transfer": transfer,
            "source": "backend metadata",
        }

    def _maybe_with_metadata(
        self, rgb: np.ndarray
    ) -> np.ndarray | tuple[np.ndarray, dict[str, object]]:
        if self._is_10bit or self._is_fp16:
            return rgb, self._capture_metadata()
        return rgb

    def _pixel_byte_offset(self, px: int, py: int) -> int:
        bpp = 8 if self._is_fp16 else 4
        if getattr(self, "_nvidia_x_tiled", False):
            return _nvidia_x_tiled_pixel_offset(px, py, self._width, bpp=bpp)
        return py * self._pitch_bytes + px * bpp

    def _read_pixel_word(self, buf: Any, pixel_base: int) -> int:
        return (
            int(buf[pixel_base])
            | (int(buf[pixel_base + 1]) << 8)
            | (int(buf[pixel_base + 2]) << 16)
            | (int(buf[pixel_base + 3]) << 24)
        )

    def _accumulate_pixel(
        self,
        buf: Any,
        pixel_base: int,
        *,
        sum_r: int | float,
        sum_g: int | float,
        sum_b: int | float,
    ) -> tuple:
        if self._is_fp16:
            word1 = int(buf[pixel_base + 2]) | (int(buf[pixel_base + 3]) << 8)
            word2 = int(buf[pixel_base + 4]) | (int(buf[pixel_base + 5]) << 8)
            word3 = int(buf[pixel_base + 6]) | (int(buf[pixel_base + 7]) << 8)
            b_half = _decode_fp16_half(word1)
            g_half = _decode_fp16_half(word2)
            r_half = _decode_fp16_half(word3)
            if math.isfinite(b_half) and math.isfinite(g_half) and math.isfinite(r_half):
                return sum_r + r_half, sum_g + g_half, sum_b + b_half
            return sum_r, sum_g, sum_b
        if self._is_10bit:
            word = self._read_pixel_word(buf, pixel_base)
            r10, g10, b10 = _decode_10bit_pixel(word, rgb_order=self._rgb_order)
            return sum_r + r10, sum_g + g10, sum_b + b10
        return (
            sum_r + buf[pixel_base + self._r_byte],
            sum_g + buf[pixel_base + self._g_byte],
            sum_b + buf[pixel_base + self._b_byte],
        )

    def _finalize_patch_color(
        self, sum_r: int, sum_g: int, sum_b: int, n_pixels: int
    ) -> np.ndarray:
        if n_pixels <= 0:
            return np.zeros(3, dtype=np.uint8)
        if self._is_fp16:
            return _fp16_zone_to_uint8(sum_r / n_pixels, sum_g / n_pixels, sum_b / n_pixels)
        if self._is_10bit:
            avg = (
                np.array(
                    [sum_r / float(n_pixels), sum_g / float(n_pixels), sum_b / float(n_pixels)],
                    dtype=np.float32,
                )
                / 1023.0
            )
            return avg
        return np.array(
            [sum_r // n_pixels, sum_g // n_pixels, sum_b // n_pixels],
            dtype=np.uint8,
        )

    def _ensure_framebuffer_current(self) -> None:
        # When initialised via the DRM helper binary we trust the FB is
        # still current — the helper verified it and KWin won't reassign
        # CRTCs mid-stream.  Skip the GETCRTC ioctl which requires master
        # context on NVIDIA.
        if getattr(self, "_helper_dma_mmap", False) or getattr(self, "_fd_cloned", False):
            return
        if self._helper_dma_mmap:
            helper_info = request_helper_mmap(
                card_path=self._card_path,
                fb_id=self._fb_id if self._fb_id > 0 else 0,
            )
            if helper_info is None:
                raise KMSGrabError("DRM helper remount failed")
            if (
                int(helper_info.fb_id) == self._fb_id
                and self._mapped_ptr is not None
                and self._mapped_ptr != 0
            ):
                return
            self._unmap_framebuffer()
            self._apply_helper_mmap(helper_info)
            self._remount_count += 1
            return
        if self._fd < 0:
            raise KMSGrabError("DRMZoneSampler: device not open")
        crtc = _DrmModeCrtc()
        crtc.crtc_id = int(self._crtc_id)
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
        except OSError as exc:
            if self._maybe_reopen_drm_fd():
                try:
                    fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
                except OSError as retry_exc:
                    raise KMSGrabError(
                        f"DRM_IOCTL_MODE_GETCRTC failed for CRTC {self._crtc_id}"
                    ) from retry_exc
            else:
                raise KMSGrabError(
                    f"DRM_IOCTL_MODE_GETCRTC failed for CRTC {self._crtc_id}"
                ) from exc
        fb_id = int(crtc.fb_id)
        if fb_id == 0:
            raise KMSGrabError("CRTC has no active framebuffer")
        width = int(crtc.mode.hdisplay)
        height = int(crtc.mode.vdisplay)
        if (
            fb_id == self._fb_id
            and width == self._width
            and height == self._height
            and self._mapped_ptr is not None
            and self._mapped_ptr != 0
        ):
            return
        self._unmap_framebuffer()
        self._attach_framebuffer(crtc=crtc, fb_id=fb_id)
        self._remount_count += 1
        _log.debug(
            "DRMZoneSampler: remounted framebuffer fb_id=%s size=%dx%d remounts=%s",
            self._fb_id,
            self._width,
            self._height,
            self._remount_count,
        )

    def _find_active_crtc(
        self,
        *,
        buf: Any,
        struct_sz: int,
        count_crtcs: int,
        count_connectors: int,
        count_fbs: int,
    ) -> int:
        """Return the first connected CRTC id, preferring active ones."""
        if count_crtcs == 0:
            raise KMSGrabError("no CRTCs available")

        # Read CRTC id list from the buffer at known offset.
        # Kernel array order: fb_ids, crtc_ids, connector_ids, encoder_ids.
        _crtc_offset = struct_sz + count_fbs * 4
        crtc_ids: list[int] = [
            int(ctypes.c_uint32.from_buffer(buf, _crtc_offset + i * 4).value)
            for i in range(count_crtcs)
        ]

        # Quick check: if there's only one CRTC, use it directly
        if count_crtcs == 1:
            return crtc_ids[0]

        # Read connector id list from buffer offsets
        _conn_offset = _crtc_offset + count_crtcs * 4
        connector_ids: list[int] = [
            int(ctypes.c_uint32.from_buffer(buf, _conn_offset + i * 4).value)
            for i in range(count_connectors)
        ]

        for cid in connector_ids:
            conn = _DrmModeGetConnector()
            conn.connector_id = cid
            try:
                fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCONNECTOR, conn)
            except OSError:
                continue

            if conn.connection != DRM_MODE_CONNECTED:
                continue

            enc_id = conn.encoder_id
            if enc_id == 0:
                continue

            enc = _DrmModeGetEncoder()
            enc.encoder_id = enc_id
            try:
                fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETENCODER, enc)
            except OSError:
                continue

            if enc.crtc_id != 0:
                # Verify this CRTC id is in our list
                for tid in crtc_ids:
                    if tid == enc.crtc_id:
                        _log.debug(
                            "DRMZoneSampler: selected CRTC %d via connected "
                            "connector %d / encoder %d",
                            enc.crtc_id,
                            cid,
                            enc_id,
                        )
                        return int(enc.crtc_id)

        # Fallback: return first CRTC (will likely have a valid fb)
        _log.debug(
            "DRMZoneSampler: no connected CRTC found via connectors; using first CRTC %d",
            crtc_ids[0],
        )
        return crtc_ids[0]

    def _find_active_fb_via_planes(self) -> tuple[int, int]:
        cap = _DrmSetClientCap()
        cap.capability = DRM_CLIENT_CAP_UNIVERSAL_PLANES
        cap.value = 1
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_SET_CLIENT_CAP, cap)
        except OSError as exc:
            _log.debug("DRM_IOCTL_SET_CLIENT_CAP (universal planes) failed: %s", exc)
            return 0, 0

        res1 = _DrmModeGetPlaneRes()
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETPLANERESOURCES, res1)
        except OSError as exc:
            _log.debug("DRM_IOCTL_MODE_GETPLANERESOURCES failed: %s", exc)
            return 0, 0

        count_planes = int(res1.count_planes)
        if count_planes <= 0:
            return 0, 0

        plane_ids = (ctypes.c_uint32 * count_planes)()
        res2 = _DrmModeGetPlaneRes()
        res2.count_planes = count_planes
        res2.plane_id_ptr = ctypes.addressof(plane_ids)
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETPLANERESOURCES, res2)
        except OSError as exc:
            _log.debug("DRM_IOCTL_MODE_GETPLANERESOURCES (phase 2) failed: %s", exc)
            return 0, 0

        for i in range(count_planes):
            plane = _DrmModeGetPlane()
            plane.plane_id = int(plane_ids[i])
            try:
                fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETPLANE, plane)
            except OSError:
                continue
            fb_id = int(plane.fb_id)
            crtc_id = int(plane.crtc_id)
            if fb_id != 0 and crtc_id != 0:
                _log.debug(
                    "DRMZoneSampler: selected FB %d via plane %d / CRTC %d",
                    fb_id,
                    plane.plane_id,
                    crtc_id,
                )
                return fb_id, crtc_id

        return 0, 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_zone_patches(
        self, centers: list[tuple[int, int]]
    ) -> np.ndarray | tuple[np.ndarray, dict[str, object]]:
        """Return an ``(N, 3) uint8`` array of zone-average colours.

        Each zone is sampled from a 5×5 pixel patch centred on the given
        ``(x, y)`` coordinate (clamped to the framebuffer bounds).  The
        patch is read directly from the mmap'd framebuffer.
        """
        self._ensure_framebuffer_current()
        if self._mapped_ptr is None or self._mapped_ptr == 0:
            raise KMSGrabError("DRMZoneSampler: framebuffer not mapped")

        n_zones = len(centers)
        if self._is_10bit:
            out = np.zeros((n_zones, 3), dtype=np.float32)
        else:
            out = np.zeros((n_zones, 3), dtype=np.uint8)

        if n_zones == 0:
            return self._maybe_with_metadata(out)

        buf = ctypes.cast(
            ctypes.c_void_p(self._mapped_ptr),
            ctypes.POINTER(ctypes.c_uint8),
        )

        w = self._width
        h = self._height

        for i, (cx, cy) in enumerate(centers):
            x0 = max(0, int(cx) - _PATCH_RADIUS)
            y0 = max(0, int(cy) - _PATCH_RADIUS)
            x1 = min(w, int(cx) + _PATCH_RADIUS + 1)
            y1 = min(h, int(cy) + _PATCH_RADIUS + 1)

            n_pixels = 0
            sum_r = 0
            sum_g = 0
            sum_b = 0

            for py in range(y0, y1):
                for px in range(x0, x1):
                    pixel_base = self._pixel_byte_offset(px, py)
                    sum_r, sum_g, sum_b = self._accumulate_pixel(
                        buf,
                        pixel_base,
                        sum_r=sum_r,
                        sum_g=sum_g,
                        sum_b=sum_b,
                    )
                    n_pixels += 1

            out[i] = self._finalize_patch_color(sum_r, sum_g, sum_b, n_pixels)

        return self._maybe_with_metadata(out)

    def capture_zone_rects(
        self, rects: list[tuple[int, int, int, int]]
    ) -> np.ndarray | tuple[np.ndarray, dict[str, object]]:
        """Return ``(N, 3) uint8`` zone colours averaged over each display rectangle."""
        self._ensure_framebuffer_current()
        if self._mapped_ptr is None or self._mapped_ptr == 0:
            raise KMSGrabError("DRMZoneSampler: framebuffer not mapped")

        n_zones = len(rects)
        if self._is_fp16 or self._is_10bit:
            out = np.zeros((n_zones, 3), dtype=np.float32)
        else:
            out = np.zeros((n_zones, 3), dtype=np.uint8)
        if n_zones == 0:
            return self._maybe_with_metadata(out)

        buf = ctypes.cast(
            ctypes.c_void_p(self._mapped_ptr),
            ctypes.POINTER(ctypes.c_uint8),
        )

        w = self._width
        h = self._height

        for i, (rx, ry, rw, rh) in enumerate(rects):
            x0 = max(0, min(w, int(rx)))
            y0 = max(0, min(h, int(ry)))
            x1 = max(x0, min(w, int(rx) + max(1, int(rw))))
            y1 = max(y0, min(h, int(ry) + max(1, int(rh))))
            if x1 <= x0 or y1 <= y0:
                continue

            n_pixels = 0
            if self._is_fp16 or self._is_10bit:
                sum_r = 0.0
                sum_g = 0.0
                sum_b = 0.0
            else:
                sum_r = 0
                sum_g = 0
                sum_b = 0
            sum_linear = np.zeros(3, dtype=np.float64)
            for py in range(y0, y1):
                for px in range(x0, x1):
                    pixel_base = self._pixel_byte_offset(px, py)
                    if self._is_fp16 or self._is_10bit:
                        sum_r, sum_g, sum_b = self._accumulate_pixel(
                            buf,
                            pixel_base,
                            sum_r=sum_r,
                            sum_g=sum_g,
                            sum_b=sum_b,
                        )
                    else:
                        rgb_u8 = np.array(
                            [
                                buf[pixel_base + self._r_byte],
                                buf[pixel_base + self._g_byte],
                                buf[pixel_base + self._b_byte],
                            ],
                            dtype=np.uint8,
                        )
                        sum_linear += srgb_u8_to_linear01(rgb_u8[None, :])[0]
                    n_pixels += 1

            if n_pixels > 0:
                if self._is_fp16:
                    out[i] = np.array([sum_r, sum_g, sum_b], dtype=np.float32) / float(n_pixels)
                elif self._is_10bit:
                    avg = np.array(
                        [sum_r, sum_g, sum_b],
                        dtype=np.float32,
                    ) / (float(n_pixels) * 1023.0)
                    out[i] = avg
                else:
                    avg_linear = (sum_linear / float(n_pixels)).astype(np.float32, copy=False)
                    out[i] = linear01_to_srgb_u8(avg_linear)

        return self._maybe_with_metadata(out)

    @property
    def dma_buf_fd(self) -> int:
        return int(self._dma_buf_fd)

    @property
    def capture_metadata(self) -> dict[str, object]:
        return self._capture_metadata()

    @property
    def is_10bit(self) -> bool:
        return bool(self._is_10bit)

    @property
    def width(self) -> int:
        """Framebuffer width in pixels (from the current mode)."""
        return self._width

    @property
    def height(self) -> int:
        """Framebuffer height in pixels (from the current mode)."""
        return self._height

    @property
    def active_fb_id(self) -> int:
        return int(self._fb_id)

    @property
    def remount_count(self) -> int:
        return int(self._remount_count)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release mmap and close the DRM file descriptor."""
        self._unmap_framebuffer()
        if self._dma_buf_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._dma_buf_fd)
            self._dma_buf_fd = -1
        if self._fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> DRMZoneSampler:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        self.close()
        return False
