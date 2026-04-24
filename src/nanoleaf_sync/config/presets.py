from __future__ import annotations

from dataclasses import dataclass

# Canonical preset values
LAYOUT_PRESET_EDGE_STRIP = "edge_strip"
LAYOUT_PRESET_HORIZONTAL_DEBUG = "horizontal_debug"

EDGE_LOCALITY_TIGHT = "tight"
EDGE_LOCALITY_BALANCED = "balanced"
EDGE_LOCALITY_WIDE = "wide"

SAMPLING_QUALITY_LOW = "low"
SAMPLING_QUALITY_BALANCED = "balanced"
SAMPLING_QUALITY_HIGH = "high"

MOTION_PRESET_CALM = "calm"
MOTION_PRESET_RESPONSIVE = "responsive"
MOTION_PRESET_DYNAMIC = "dynamic"

COLOR_STYLE_NATURAL = "natural"
COLOR_STYLE_VIVID = "vivid"
COLOR_STYLE_PUNCHY = "punchy"

DISPLAY_PRESET_SDR = "sdr"
DISPLAY_PRESET_HDR = "hdr"
DISPLAY_PRESET_AUTO = "auto"

LAYOUT_PRESETS = (
    LAYOUT_PRESET_EDGE_STRIP,
    LAYOUT_PRESET_HORIZONTAL_DEBUG,
)
EDGE_LOCALITY_PRESETS = (EDGE_LOCALITY_TIGHT, EDGE_LOCALITY_BALANCED, EDGE_LOCALITY_WIDE)
SAMPLING_QUALITY_PRESETS = (
    SAMPLING_QUALITY_LOW,
    SAMPLING_QUALITY_BALANCED,
    SAMPLING_QUALITY_HIGH,
)
MOTION_PRESETS = (MOTION_PRESET_CALM, MOTION_PRESET_RESPONSIVE, MOTION_PRESET_DYNAMIC)
COLOR_STYLE_PRESETS = (COLOR_STYLE_NATURAL, COLOR_STYLE_VIVID, COLOR_STYLE_PUNCHY)
DISPLAY_PRESETS = (DISPLAY_PRESET_SDR, DISPLAY_PRESET_HDR, DISPLAY_PRESET_AUTO)


@dataclass(frozen=True)
class EdgeLocalityProfile:
    edge_thickness_target: float
    edge_bias: float
    center_sigma: float


@dataclass(frozen=True)
class MotionProfile:
    smoothing_multiplier: float
    smoothing_speed_multiplier: float


def normalize_preset(value: object, *, allowed: tuple[str, ...], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def normalize_layout_preset(value: object) -> str:
    aliases = {
        "edge": LAYOUT_PRESET_EDGE_STRIP,
        "edge-weighted": LAYOUT_PRESET_EDGE_STRIP,
        "edge_strip": LAYOUT_PRESET_EDGE_STRIP,
        "horizontal": LAYOUT_PRESET_HORIZONTAL_DEBUG,
        "horizontal_debug": LAYOUT_PRESET_HORIZONTAL_DEBUG,
    }
    return aliases.get(str(value or "").strip().lower(), LAYOUT_PRESET_EDGE_STRIP)


def edge_locality_profile(locality: str) -> EdgeLocalityProfile:
    normalized = normalize_preset(locality, allowed=EDGE_LOCALITY_PRESETS, default=EDGE_LOCALITY_BALANCED)
    if normalized == EDGE_LOCALITY_TIGHT:
        return EdgeLocalityProfile(edge_thickness_target=0.055, edge_bias=8.0, center_sigma=0.18)
    if normalized == EDGE_LOCALITY_WIDE:
        return EdgeLocalityProfile(edge_thickness_target=0.090, edge_bias=4.2, center_sigma=0.34)
    return EdgeLocalityProfile(edge_thickness_target=0.070, edge_bias=5.8, center_sigma=0.25)


def sampling_quality_to_zone_stride(quality: str) -> int:
    normalized = normalize_preset(quality, allowed=SAMPLING_QUALITY_PRESETS, default=SAMPLING_QUALITY_BALANCED)
    return {SAMPLING_QUALITY_LOW: 4, SAMPLING_QUALITY_BALANCED: 2, SAMPLING_QUALITY_HIGH: 1}[normalized]


def motion_profile(motion_preset: str) -> MotionProfile:
    normalized = normalize_preset(motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE)
    if normalized == MOTION_PRESET_CALM:
        return MotionProfile(smoothing_multiplier=0.75, smoothing_speed_multiplier=0.70)
    if normalized == MOTION_PRESET_DYNAMIC:
        return MotionProfile(smoothing_multiplier=1.15, smoothing_speed_multiplier=1.35)
    return MotionProfile(smoothing_multiplier=1.0, smoothing_speed_multiplier=1.0)


def analyzer_mode_for_presets(*, motion_preset: str, color_style: str) -> str:
    motion = normalize_preset(motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE)
    style = normalize_preset(color_style, allowed=COLOR_STYLE_PRESETS, default=COLOR_STYLE_NATURAL)
    # Natural style is accuracy-first and should preserve localized edge sampling behavior.
    if style == COLOR_STYLE_NATURAL:
        return "balanced"
    if motion == MOTION_PRESET_DYNAMIC and style == COLOR_STYLE_PUNCHY:
        return "hyper"
    return "dynamic"
