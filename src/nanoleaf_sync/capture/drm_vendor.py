"""DRM GPU vendor detection and shared scanout layout helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from nanoleaf_sync.capture._drm_helper_bridge import is_nvidia_x_tiled_modifier

_log = logging.getLogger(__name__)

DrmVendor = Literal["nvidia", "amd", "intel", "unknown"]
ValidationTier = Literal["validated", "unvalidated"]
ModifierLayout = Literal["linear", "nvidia_x_tiled", "intel_ccs", "amd_tiled"]

_PCI_VENDOR_NVIDIA = 0x10DE
_PCI_VENDOR_AMD = 0x1002
_PCI_VENDOR_INTEL = 0x8086

_MODIFIER_VENDOR_NVIDIA = 0x03
_MODIFIER_VENDOR_INTEL = 0x01
_MODIFIER_VENDOR_AMD = 0x02


def detect_drm_vendor(card_path: str | None = None) -> DrmVendor:
    """Detect DRM GPU vendor from sysfs PCI id."""

    try:
        card = Path(str(card_path or _default_drm_card_path()))
    except OSError:
        return "unknown"
    device = card / "device" / "vendor"
    if not device.is_file():
        return "unknown"
    try:
        raw = device.read_text(encoding="ascii").strip().lower()
    except OSError:
        return "unknown"
    if raw.startswith("0x"):
        vendor_id = int(raw, 16)
    else:
        try:
            vendor_id = int(raw, 16)
        except ValueError:
            return "unknown"
    if vendor_id == _PCI_VENDOR_NVIDIA:
        return "nvidia"
    if vendor_id == _PCI_VENDOR_AMD:
        return "amd"
    if vendor_id == _PCI_VENDOR_INTEL:
        return "intel"
    return "unknown"


def vendor_validation_tier(vendor: DrmVendor) -> ValidationTier:
    return "validated" if vendor == "nvidia" else "unvalidated"


def modifier_layout(modifier: int, *, vendor: DrmVendor | None = None) -> ModifierLayout:
    mod = int(modifier)
    if mod in {0, 1 << 56}:
        return "linear"
    vendor_byte = (mod >> 56) & 0xFF
    if vendor_byte == _MODIFIER_VENDOR_NVIDIA or is_nvidia_x_tiled_modifier(mod):
        return "nvidia_x_tiled"
    if vendor_byte == _MODIFIER_VENDOR_INTEL:
        return "intel_ccs"
    if vendor_byte == _MODIFIER_VENDOR_AMD or (vendor == "amd" and mod != 0):
        return "amd_tiled"
    return "linear"


def nvidia_x_tiled_pixel_offset(px: int, py: int, frame_width: int, *, bpp: int = 4) -> int:
    tilex = 16
    tiley = 128
    sno = (px // tilex) + (py // tiley) * (frame_width // tilex)
    ord_ = (px % tilex) + (py % tiley) * tilex
    return (sno * tilex * tiley + ord_) * bpp


def pixel_byte_offset(
    *,
    px: int,
    py: int,
    pitch_bytes: int,
    bpp: int,
    frame_width: int,
    modifier: int,
    vendor: DrmVendor,
) -> int:
    layout = modifier_layout(modifier, vendor=vendor)
    if layout == "nvidia_x_tiled":
        return nvidia_x_tiled_pixel_offset(px, py, frame_width, bpp=bpp)
    # ponytail: Intel CCS and AMD tiled scanout use pitch-linear until proven otherwise.
    return py * pitch_bytes + px * bpp


def resolve_drm_primaries_label() -> str:
    from nanoleaf_sync.color.primaries import get_display_primaries

    chroma = get_display_primaries()
    if chroma is None:
        return "bt709"
    area = abs(
        chroma.rx * (chroma.gy - chroma.by)
        + chroma.gx * (chroma.by - chroma.ry)
        + chroma.bx * (chroma.ry - chroma.gy)
    )
    if area < 0.02:
        return "bt709"
    wx, wy = chroma.wx, chroma.wy
    if wx > 0.28 and wy > 0.33:
        return "bt2020"
    if chroma.gx > 0.25 and chroma.gy > 0.65:
        return "bt709"
    return "bt2020"


_FOURCC_NV_AB4H = 0x48344241
_10BIT_FOURCCS = frozenset({0x30334241, 0x30334258, 0x30335241, 0x30335258})
_FP16_FOURCCS = frozenset({_FOURCC_NV_AB4H})


def scanout_metadata_for_fourcc(
    fourcc: int,
    *,
    vendor: DrmVendor,
    connector_colorspace: str | None = None,
) -> dict[str, object]:
    if fourcc in _FP16_FOURCCS:
        bit_depth = 16
        transfer = "linear"
        primaries = "bt2020"
    elif fourcc in _10BIT_FOURCCS:
        bit_depth = 10
        transfer = "gamma22"
        primaries = "bt2020"
    else:
        bit_depth = 8
        transfer = "srgb"
        primaries = resolve_drm_primaries_label()

    if connector_colorspace:
        normalized = connector_colorspace.strip().lower()
        if "2020" in normalized:
            primaries = "bt2020"
        elif (
            "709" in normalized or "srgb" in normalized or "p3" in normalized or "dci" in normalized
        ):
            primaries = "bt709"

    return {
        "fourcc": int(fourcc),
        "bit_depth": bit_depth,
        "primaries": primaries,
        "transfer": transfer,
        "source": "backend metadata",
        "display_referred": True,
        "drm_vendor": vendor,
        "validation_tier": vendor_validation_tier(vendor),
    }


def _default_drm_card_path() -> str:
    import os

    override = os.environ.get("NANOLEAF_DRM_CARD", "").strip()
    if override:
        return override
    for candidate in sorted(Path("/dev/dri").glob("card*")):
        if candidate.is_char_device():
            return str(candidate)
    return "/dev/dri/card0"


def drm_helper_ready() -> bool:
    from nanoleaf_sync.capture._drm_helper_bridge import drm_helper_binary_ready

    if not Path(_default_drm_card_path()).exists():
        return False
    return drm_helper_binary_ready()


_DRM_CONNECTOR_TYPE_NAMES: dict[int, str] = {
    1: "VGA",
    2: "DVI-I",
    3: "DVI-D",
    4: "DVI-A",
    5: "Composite",
    6: "S-Video",
    7: "LVDS",
    8: "Component",
    9: "DIN",
    10: "DisplayPort",
    11: "HDMI-A",
    12: "HDMI-B",
    13: "TV",
    14: "eDP",
    15: "Virtual",
    16: "DSI",
    17: "DPI",
}


def connector_drm_name(*, connector_type: int, connector_type_id: int) -> str:
    base = _DRM_CONNECTOR_TYPE_NAMES.get(int(connector_type), f"UNKNOWN-{int(connector_type)}")
    return f"{base}-{int(connector_type_id)}"


def connector_matches_capture_monitor(
    *,
    connector_type: int,
    connector_type_id: int,
    capture_monitor: str,
) -> bool:
    requested = str(capture_monitor or "").strip()
    if not requested:
        return True
    label = connector_drm_name(
        connector_type=connector_type,
        connector_type_id=connector_type_id,
    )
    normalized = requested.strip().lower()
    return normalized == label.lower() or normalized in label.lower()
