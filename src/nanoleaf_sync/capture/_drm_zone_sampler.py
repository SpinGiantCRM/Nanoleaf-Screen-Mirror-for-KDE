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

import ctypes
import fcntl
import logging
import os
from typing import Any, List, Optional, Tuple

import numpy as np

from nanoleaf_sync.capture.errors import KMSGrabError

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
    0xA2,
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

# Connection states  (drm_mode.h)
DRM_MODE_CONNECTED = 1

# Fourcc codes for the 32 bpp formats this module supports
_FOURCC_XR24 = 0x34325258  # X8 R8 G8 B8  (little-endian byte order: B, G, R, X)
_FOURCC_AR24 = 0x34325241  # A8 R8 G8 B8
_FOURCC_XB24 = 0x34324258  # X8 B8 G8 R8  (little-endian byte order: R, G, B, X)
_FOURCC_AB24 = 0x34324241  # A8 B8 G8 R8

_PATCH_RADIUS = 2  # 5×5 patch → radius 2


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
        self._mapped_ptr: Optional[int] = None
        self._mapped_size: int = 0
        self._width: int = 0
        self._height: int = 0
        self._pitch_bytes: int = 0
        self._fourcc: int = 0
        self._r_byte: int = 2
        self._g_byte: int = 1
        self._b_byte: int = 0
        self._libc: Any = None

        try:
            self._init()
        except Exception as exc:
            self.close()
            raise KMSGrabError(f"DRMZoneSampler init failed for {self._card_path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init(self) -> None:
        self._fd = os.open(self._card_path, os.O_RDONLY)
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
        crtc.crtc_id = crtc_id
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETCRTC, crtc)
        except OSError as exc:
            raise KMSGrabError(f"DRM_IOCTL_MODE_GETCRTC failed for CRTC {crtc_id}") from exc

        fb_id = crtc.fb_id
        if fb_id == 0:
            raise KMSGrabError("CRTC has no active framebuffer")

        self._width = int(crtc.mode.hdisplay)
        self._height = int(crtc.mode.vdisplay)
        if self._width <= 0 or self._height <= 0:
            raise KMSGrabError(f"invalid CRTC mode dimensions: {self._width}x{self._height}")

        # 4. Get framebuffer metadata (fourcc, pitch, handle)
        fb2 = _DrmModeFbCmd2()
        fb2.fb_id = fb_id
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_GETFB2, fb2)
        except OSError:
            raise KMSGrabError(f"DRM_IOCTL_MODE_GETFB2 failed for FB {fb_id}")

        self._fourcc = int(fb2.pixel_format)
        self._pitch_bytes = int(fb2.pitches[0])
        handle = int(fb2.handles[0])
        buff_offset = int(fb2.offsets[0])

        # 5. Validate pixel format
        if self._fourcc not in (
            _FOURCC_XR24,
            _FOURCC_AR24,
            _FOURCC_XB24,
            _FOURCC_AB24,
        ):
            raise KMSGrabError(
                f"unsupported DRM fourcc 0x{self._fourcc:08X}; expected XR24/AR24/XB24/AB24"
            )

        # Byte order for R/G/B extraction:
        # XR24 / AR24: LE bytes [0]=B, [1]=G, [2]=R, [3]=X/A
        # XB24 / AB24: LE bytes [0]=R, [1]=G, [2]=B, [3]=X/A
        if self._fourcc in (_FOURCC_XR24, _FOURCC_AR24):
            self._b_byte, self._g_byte, self._r_byte = 0, 1, 2
        else:
            self._r_byte, self._g_byte, self._b_byte = 0, 1, 2

        # 6. Map the dumb/GEM buffer
        _map_dumb = _DrmModeMapDumb()
        _map_dumb.handle = handle
        try:
            fcntl.ioctl(self._fd, DRM_IOCTL_MODE_MAP_DUMB, _map_dumb)
        except OSError as exc:
            raise KMSGrabError(f"DRM_IOCTL_MODE_MAP_DUMB failed for handle {handle}") from exc

        self._mapped_size = int(self._height) * int(self._pitch_bytes) + int(buff_offset)
        PROT_READ = 0x01
        MAP_SHARED = 0x01
        MAP_FAILED_VALUE = ctypes.c_void_p(-1).value or -1

        _ptr = self._libc.mmap(
            None,
            ctypes.c_size_t(self._mapped_size),
            ctypes.c_int(PROT_READ),
            ctypes.c_int(MAP_SHARED),
            ctypes.c_int(self._fd),
            ctypes.c_long(_map_dumb.offset),
        )
        _ptr_addr: int | None = _ptr.value if _ptr else None
        if _ptr_addr is None or _ptr_addr == MAP_FAILED_VALUE:
            raise KMSGrabError("mmap of DRM framebuffer failed")

        self._mapped_ptr = _ptr_addr

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_zone_patches(self, centers: List[Tuple[int, int]]) -> np.ndarray:
        """Return an ``(N, 3) uint8`` array of zone-average colours.

        Each zone is sampled from a 5×5 pixel patch centred on the given
        ``(x, y)`` coordinate (clamped to the framebuffer bounds).  The
        patch is read directly from the mmap'd framebuffer.
        """
        if self._mapped_ptr is None or self._mapped_ptr == 0:
            raise KMSGrabError("DRMZoneSampler: framebuffer not mapped")

        n_zones = len(centers)
        out = np.zeros((n_zones, 3), dtype=np.uint8)

        if n_zones == 0:
            return out

        buf = ctypes.cast(
            ctypes.c_void_p(self._mapped_ptr),
            ctypes.POINTER(ctypes.c_uint8),
        )

        w = self._width
        h = self._height
        pitch = self._pitch_bytes
        r_off = self._r_byte
        g_off = self._g_byte
        b_off = self._b_byte

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
                row_base = py * pitch
                for px in range(x0, x1):
                    pixel_base = row_base + px * 4
                    sum_r += buf[pixel_base + r_off]
                    sum_g += buf[pixel_base + g_off]
                    sum_b += buf[pixel_base + b_off]
                    n_pixels += 1

            if n_pixels > 0:
                out[i, 0] = int(sum_r // n_pixels)
                out[i, 1] = int(sum_g // n_pixels)
                out[i, 2] = int(sum_b // n_pixels)
            # else: patch empty → stays [0,0,0]

        return out

    @property
    def width(self) -> int:
        """Framebuffer width in pixels (from the current mode)."""
        return self._width

    @property
    def height(self) -> int:
        """Framebuffer height in pixels (from the current mode)."""
        return self._height

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release mmap and close the DRM file descriptor."""
        if self._mapped_ptr is not None and self._mapped_ptr != 0 and self._mapped_size > 0:
            libc = self._libc
            if libc is None:
                libc = ctypes.CDLL("libc.so.6")
                libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                libc.munmap.restype = ctypes.c_int
            try:
                libc.munmap(
                    ctypes.c_void_p(self._mapped_ptr),
                    ctypes.c_size_t(self._mapped_size),
                )
            except Exception:
                _log.debug("DRM mmap munmap failed during close", exc_info=True)
            self._mapped_ptr = None
            self._mapped_size = 0

        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1

    def __enter__(self) -> DRMZoneSampler:
        return self

    def __exit__(self, *args: object) -> bool:
        self.close()
        return False
