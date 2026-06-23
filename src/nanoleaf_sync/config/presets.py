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

COLOR_STYLE_REFERENCE = "reference"
COLOR_STYLE_NATURAL = "natural"
COLOR_STYLE_AMBIENT = "ambient"
COLOR_STYLE_VIVID = "vivid"
COLOR_STYLE_PUNCHY = "punchy"

DISPLAY_PRESET_SDR = "sdr"
DISPLAY_PRESET_HDR = "hdr"
DISPLAY_PRESET_AUTO = "auto"

LIGHT_SPREAD_PRECISE = "precise"
LIGHT_SPREAD_BALANCED = "balanced"
LIGHT_SPREAD_SOFT = "soft"
LIGHT_SPREAD_OFF = "off"

SAMPLING_MODE_AUTO = "auto"
SAMPLING_MODE_AREA_AVERAGE = "area_average"
SAMPLING_MODE_EDGE_DIRECT = "edge_direct"
SAMPLING_MODE_VIVID_WEIGHTED = "vivid_weighted"
SAMPLING_MODE_PEAK_LUMA = "peak_luma"
SAMPLING_MODE_PALETTE_ADAPTIVE = "palette_adaptive"

SYNC_MODE_STANDARD = "standard"
SYNC_MODE_4D = "4d"

SYNC_MODES = (SYNC_MODE_STANDARD, SYNC_MODE_4D)

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
COLOR_STYLE_PRESETS = (
    COLOR_STYLE_REFERENCE,
    COLOR_STYLE_NATURAL,
    COLOR_STYLE_AMBIENT,
    COLOR_STYLE_VIVID,
    COLOR_STYLE_PUNCHY,
)
DISPLAY_PRESETS = (DISPLAY_PRESET_SDR, DISPLAY_PRESET_HDR, DISPLAY_PRESET_AUTO)
LIGHT_SPREAD_PRESETS = (
    LIGHT_SPREAD_OFF,
    LIGHT_SPREAD_PRECISE,
    LIGHT_SPREAD_BALANCED,
    LIGHT_SPREAD_SOFT,
)
SAMPLING_MODE_PRESETS = (
    SAMPLING_MODE_AUTO,
    SAMPLING_MODE_AREA_AVERAGE,
    SAMPLING_MODE_EDGE_DIRECT,
    SAMPLING_MODE_VIVID_WEIGHTED,
    SAMPLING_MODE_PEAK_LUMA,
    SAMPLING_MODE_PALETTE_ADAPTIVE,
)


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
    normalized = normalize_preset(
        locality, allowed=EDGE_LOCALITY_PRESETS, default=EDGE_LOCALITY_BALANCED
    )
    if normalized == EDGE_LOCALITY_TIGHT:
        return EdgeLocalityProfile(edge_thickness_target=0.055, edge_bias=8.0, center_sigma=0.18)
    if normalized == EDGE_LOCALITY_WIDE:
        return EdgeLocalityProfile(edge_thickness_target=0.090, edge_bias=4.2, center_sigma=0.34)
    return EdgeLocalityProfile(edge_thickness_target=0.070, edge_bias=5.8, center_sigma=0.25)


def sampling_quality_to_zone_stride(quality: str) -> int:
    normalized = normalize_preset(
        quality, allowed=SAMPLING_QUALITY_PRESETS, default=SAMPLING_QUALITY_BALANCED
    )
    return {SAMPLING_QUALITY_LOW: 4, SAMPLING_QUALITY_BALANCED: 2, SAMPLING_QUALITY_HIGH: 1}[
        normalized
    ]


def motion_profile(motion_preset: str) -> MotionProfile:
    normalized = normalize_preset(
        motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE
    )
    if normalized == MOTION_PRESET_CALM:
        return MotionProfile(smoothing_multiplier=0.75, smoothing_speed_multiplier=0.70)
    if normalized == MOTION_PRESET_DYNAMIC:
        return MotionProfile(smoothing_multiplier=1.15, smoothing_speed_multiplier=1.35)
    return MotionProfile(smoothing_multiplier=1.0, smoothing_speed_multiplier=1.0)


def analyzer_mode_for_presets(*, motion_preset: str, color_style: str) -> str:
    motion = normalize_preset(
        motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE
    )
    style = normalize_preset(color_style, allowed=COLOR_STYLE_PRESETS, default=COLOR_STYLE_NATURAL)
    if style in {COLOR_STYLE_REFERENCE, COLOR_STYLE_NATURAL, COLOR_STYLE_AMBIENT}:
        return "balanced"
    if motion == MOTION_PRESET_DYNAMIC and style == COLOR_STYLE_PUNCHY:
        return "hyper"
    return "dynamic"


def is_accuracy_mode(accuracy_mode: bool, color_style: str) -> bool:
    if accuracy_mode:
        return True
    style = normalize_preset(color_style, allowed=COLOR_STYLE_PRESETS, default=COLOR_STYLE_NATURAL)
    return style in {COLOR_STYLE_REFERENCE, COLOR_STYLE_NATURAL}


def effective_light_spread(*, light_spread: str, accuracy_mode: bool, color_style: str) -> str:
    style = normalize_preset(color_style, allowed=COLOR_STYLE_PRESETS, default=COLOR_STYLE_NATURAL)
    if is_accuracy_mode(accuracy_mode, color_style) or style in {
        COLOR_STYLE_REFERENCE,
        COLOR_STYLE_NATURAL,
    }:
        return LIGHT_SPREAD_OFF
    if not is_accuracy_mode(accuracy_mode, color_style):
        return normalize_preset(
            light_spread, allowed=LIGHT_SPREAD_PRESETS, default=LIGHT_SPREAD_BALANCED
        )
    normalized = normalize_preset(
        light_spread, allowed=LIGHT_SPREAD_PRESETS, default=LIGHT_SPREAD_BALANCED
    )
    if normalized == LIGHT_SPREAD_SOFT:
        return LIGHT_SPREAD_BALANCED
    return normalized


def effective_sampling_mode(*, sampling_mode: str, color_style: str, accuracy_mode: bool) -> str:
    normalized = normalize_preset(
        sampling_mode, allowed=SAMPLING_MODE_PRESETS, default=SAMPLING_MODE_AUTO
    )
    if normalized != SAMPLING_MODE_AUTO:
        return normalized
    if is_accuracy_mode(accuracy_mode, color_style):
        return SAMPLING_MODE_EDGE_DIRECT
    style = normalize_preset(color_style, allowed=COLOR_STYLE_PRESETS, default=COLOR_STYLE_AMBIENT)
    if style in {COLOR_STYLE_REFERENCE, COLOR_STYLE_NATURAL}:
        return SAMPLING_MODE_EDGE_DIRECT
    if style == COLOR_STYLE_AMBIENT:
        return SAMPLING_MODE_PALETTE_ADAPTIVE
    if style in {COLOR_STYLE_VIVID, COLOR_STYLE_PUNCHY}:
        return SAMPLING_MODE_PALETTE_ADAPTIVE
    return SAMPLING_MODE_EDGE_DIRECT


def effective_zone_sampling_engine(
    *, zone_sampling_engine: str, accuracy_mode: bool, color_style: str
) -> str:
    if is_accuracy_mode(accuracy_mode, color_style):
        return "optimized"
    normalized = str(zone_sampling_engine or "auto").strip().lower()
    if normalized in {"auto", "legacy", "optimized"}:
        return normalized
    return "auto"


def is_four_d_sync(sync_mode: str) -> bool:
    return (
        normalize_preset(sync_mode, allowed=SYNC_MODES, default=SYNC_MODE_STANDARD) == SYNC_MODE_4D
    )


def effective_sync_mode(sync_mode: str) -> str:
    return normalize_preset(sync_mode, allowed=SYNC_MODES, default=SYNC_MODE_STANDARD)


def effective_edge_locality_for_sync(*, edge_locality: str, sync_mode: str) -> str:
    if is_four_d_sync(sync_mode):
        return EDGE_LOCALITY_TIGHT
    return normalize_preset(
        edge_locality, allowed=EDGE_LOCALITY_PRESETS, default=EDGE_LOCALITY_BALANCED
    )


def effective_light_spread_for_sync(
    *,
    light_spread: str,
    accuracy_mode: bool,
    color_style: str,
    sync_mode: str,
) -> str:
    if is_four_d_sync(sync_mode):
        spread = effective_light_spread(
            light_spread=LIGHT_SPREAD_PRECISE,
            accuracy_mode=accuracy_mode,
            color_style=color_style,
        )
        if spread == LIGHT_SPREAD_BALANCED:
            return LIGHT_SPREAD_PRECISE
        return spread
    return effective_light_spread(
        light_spread=light_spread,
        accuracy_mode=accuracy_mode,
        color_style=color_style,
    )


def effective_motion_preset_for_sync(*, motion_preset: str, sync_mode: str) -> str:
    if is_four_d_sync(sync_mode):
        return MOTION_PRESET_RESPONSIVE
    return normalize_preset(motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE)


def effective_sampling_quality_for_sync(
    *, sampling_quality: str, sync_mode: str, config_fps: int = 60
) -> str:
    if is_four_d_sync(sync_mode):
        target_fps = max(1, int(config_fps))
        if target_fps >= 120:
            return SAMPLING_QUALITY_LOW
        if target_fps >= 60:
            current = normalize_preset(
                sampling_quality,
                allowed=SAMPLING_QUALITY_PRESETS,
                default=SAMPLING_QUALITY_BALANCED,
            )
            if current == SAMPLING_QUALITY_HIGH:
                return SAMPLING_QUALITY_BALANCED
            return current
        current = normalize_preset(
            sampling_quality,
            allowed=SAMPLING_QUALITY_PRESETS,
            default=SAMPLING_QUALITY_HIGH,
        )
        if current == SAMPLING_QUALITY_HIGH:
            return SAMPLING_QUALITY_BALANCED
        return current
    return normalize_preset(
        sampling_quality,
        allowed=SAMPLING_QUALITY_PRESETS,
        default=SAMPLING_QUALITY_BALANCED,
    )


def effective_zone_sampling_stride_for_sync(
    *, sampling_quality: str, sync_mode: str, config_fps: int = 60
) -> int:
    quality = effective_sampling_quality_for_sync(
        sampling_quality=sampling_quality,
        sync_mode=sync_mode,
        config_fps=config_fps,
    )
    return sampling_quality_to_zone_stride(quality)


def effective_zone_sampling_engine_for_sync(
    *,
    zone_sampling_engine: str,
    accuracy_mode: bool,
    color_style: str,
    sync_mode: str,
) -> str:
    if is_four_d_sync(sync_mode) and not is_accuracy_mode(accuracy_mode, color_style):
        return "optimized"
    return effective_zone_sampling_engine(
        zone_sampling_engine=zone_sampling_engine,
        accuracy_mode=accuracy_mode,
        color_style=color_style,
    )


def effective_drm_zone_patch_capture(*, drm_zone_patch_capture: bool, sync_mode: str) -> bool:
    if bool(drm_zone_patch_capture):
        return True
    return is_four_d_sync(sync_mode)


def predictive_sync_enabled_for_sync(
    *, sync_mode: str, accuracy_mode: bool, color_style: str
) -> bool:
    if not is_four_d_sync(sync_mode):
        return False
    return not is_accuracy_mode(accuracy_mode, color_style)


def effective_motion_and_smoothing(
    *,
    motion_preset: str,
    smoothing: float,
    smoothing_speed: float,
    accuracy_mode: bool,
    color_style: str,
    sync_mode: str = SYNC_MODE_STANDARD,
) -> tuple[str, float, float]:
    motion_preset = effective_motion_preset_for_sync(
        motion_preset=motion_preset,
        sync_mode=sync_mode,
    )
    if not is_accuracy_mode(accuracy_mode, color_style):
        profile = motion_profile(motion_preset)
        return (
            normalize_preset(
                motion_preset, allowed=MOTION_PRESETS, default=MOTION_PRESET_RESPONSIVE
            ),
            max(0.0, min(1.0, float(smoothing) * profile.smoothing_multiplier)),
            max(0.0, min(4.0, float(smoothing_speed) * profile.smoothing_speed_multiplier)),
        )
    return (
        MOTION_PRESET_RESPONSIVE,
        max(0.35, min(1.0, float(smoothing))),
        max(0.5, min(4.0, float(smoothing_speed))),
    )
