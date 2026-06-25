"""Scene-aware smoothing/FPS profile selection."""

from __future__ import annotations

from dataclasses import dataclass

PROFILES: dict[str, dict[str, object]] = {
    "movie": {
        "color_style": "natural",
        "smoothing": 0.7,
        "smoothing_speed": 0.5,
        "light_spread": "soft",
        "fps": 30,
        "motion_preset": "calm",
    },
    "game": {
        "color_style": "vivid",
        "smoothing": 0.3,
        "smoothing_speed": 1.5,
        "light_spread": "balanced",
        "fps": 60,
        "motion_preset": "dynamic",
    },
    "presentation": {
        "color_style": "natural",
        "smoothing": 0.8,
        "smoothing_speed": 0.3,
        "light_spread": "precise",
        "fps": 15,
        "motion_preset": "calm",
    },
    "desktop": {
        "color_style": "ambient",
        "smoothing": 0.5,
        "smoothing_speed": 0.75,
        "light_spread": "balanced",
        "fps": 30,
        "motion_preset": "responsive",
    },
}


def classify_scene(
    *,
    motion: float,
    letterbox_ratio: float,
    chroma_variance: float,
) -> str:
    if letterbox_ratio > 0.08 and motion < 15.0:
        return "movie"
    if motion > 15.0:
        return "game"
    if chroma_variance < 15.0 and motion < 3.0:
        return "presentation"
    return "desktop"


@dataclass(frozen=True)
class SceneProfileBlend:
    profile_name: str
    blend: float
