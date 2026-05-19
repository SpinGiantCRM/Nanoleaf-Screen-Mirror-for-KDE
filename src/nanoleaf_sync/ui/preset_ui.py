from __future__ import annotations

from nanoleaf_sync.config.presets import (
    COLOR_STYLE_AMBIENT,
    COLOR_STYLE_NATURAL,
    COLOR_STYLE_PUNCHY,
    COLOR_STYLE_REFERENCE,
    COLOR_STYLE_VIVID,
    DISPLAY_PRESET_AUTO,
    DISPLAY_PRESET_HDR,
    DISPLAY_PRESET_SDR,
    EDGE_LOCALITY_BALANCED,
    EDGE_LOCALITY_TIGHT,
    EDGE_LOCALITY_WIDE,
    LAYOUT_PRESET_EDGE_STRIP,
    LIGHT_SPREAD_BALANCED,
    LIGHT_SPREAD_PRECISE,
    LIGHT_SPREAD_SOFT,
    MOTION_PRESET_CALM,
    MOTION_PRESET_DYNAMIC,
    MOTION_PRESET_RESPONSIVE,
    SAMPLING_QUALITY_BALANCED,
    SAMPLING_QUALITY_HIGH,
    SAMPLING_QUALITY_LOW,
)

LAYOUT_PRESET_LABELS: tuple[tuple[str, str], ...] = (("Edge strip", LAYOUT_PRESET_EDGE_STRIP),)
EDGE_LOCALITY_LABELS: tuple[tuple[str, str], ...] = (
    ("Tight", EDGE_LOCALITY_TIGHT),
    ("Balanced", EDGE_LOCALITY_BALANCED),
    ("Wide", EDGE_LOCALITY_WIDE),
)
SAMPLING_QUALITY_LABELS: tuple[tuple[str, str], ...] = (
    ("Low", SAMPLING_QUALITY_LOW),
    ("Balanced", SAMPLING_QUALITY_BALANCED),
    ("High", SAMPLING_QUALITY_HIGH),
)
MOTION_PRESET_LABELS: tuple[tuple[str, str], ...] = (
    ("Calm", MOTION_PRESET_CALM),
    ("Responsive", MOTION_PRESET_RESPONSIVE),
    ("Dynamic", MOTION_PRESET_DYNAMIC),
)
COLOR_STYLE_LABELS: tuple[tuple[str, str], ...] = (
    ("Reference", COLOR_STYLE_REFERENCE),
    ("Natural", COLOR_STYLE_NATURAL),
    ("Ambient (recommended)", COLOR_STYLE_AMBIENT),
    ("Vivid", COLOR_STYLE_VIVID),
    ("Punchy", COLOR_STYLE_PUNCHY),
)

LIGHT_SPREAD_LABELS: tuple[tuple[str, str], ...] = (
    ("Precise", LIGHT_SPREAD_PRECISE),
    ("Balanced", LIGHT_SPREAD_BALANCED),
    ("Soft", LIGHT_SPREAD_SOFT),
)

DISPLAY_PRESET_LABELS: tuple[tuple[str, str], ...] = (
    ("SDR", DISPLAY_PRESET_SDR),
    ("HDR", DISPLAY_PRESET_HDR),
    ("Auto", DISPLAY_PRESET_AUTO),
)

PERFORMANCE_PRIORITY_LABELS: tuple[tuple[str, str], ...] = (
    ("Normal", "normal"),
    ("High", "high"),
    ("Very high experimental", "very_high_experimental"),
)


def labels(options: tuple[tuple[str, str], ...]) -> list[str]:
    return [label for label, _value in options]


def value_for_label(options: tuple[tuple[str, str], ...], label: str, *, default: str) -> str:
    lookup = {text: value for text, value in options}
    return lookup.get(str(label), default)


def label_for_value(options: tuple[tuple[str, str], ...], value: str, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    for text, candidate in options:
        if candidate == normalized:
            return text
    return default
