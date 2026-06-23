from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SAMPLING_MODE_PALETTE_ADAPTIVE, effective_sampling_mode
from nanoleaf_sync.runtime.palette_adaptive import palette_adaptive_zone_color
from nanoleaf_sync.runtime.palette_temporal import ZonePaletteTemporalState
from nanoleaf_sync.runtime.zones import zone_colors_array, zone_colors_array_with_meta


def _sample_patch(patch: np.ndarray, **kwargs: object) -> tuple[np.ndarray, object]:
    color, diag, *_rest = palette_adaptive_zone_color(patch, **kwargs)
    return color, diag


def _green_with_white_text_patch() -> np.ndarray:
    patch = np.full((80, 120, 3), np.array([40, 180, 60], dtype=np.uint8), dtype=np.uint8)
    patch[10:70, 20:100, :] = np.array([255, 255, 255], dtype=np.uint8)
    patch[12:18, 24:96, :] = np.array([40, 180, 60], dtype=np.uint8)
    return patch


def test_green_region_with_white_text_stays_green() -> None:
    patch = _green_with_white_text_patch()
    color, diag = _sample_patch(patch)
    assert int(color[1]) > int(color[0])
    assert int(color[1]) > int(color[2])
    assert float(np.mean(color)) < 220.0
    assert diag.selected_sampling_algorithm in {
        "dominant_saturated_hue",
        "saturated_highlight",
        "area_mean",
    }
    assert diag.neutral_white_coverage > 0.1


def test_mostly_white_ui_ignores_tiny_coloured_specks() -> None:
    patch = np.full((80, 120, 3), 245, dtype=np.uint8)
    patch[30:34, 50:54, :] = np.array([255, 0, 0], dtype=np.uint8)
    patch[55:58, 70:73, :] = np.array([0, 0, 255], dtype=np.uint8)
    color, diag = _sample_patch(patch)
    assert float(np.std(color)) < 12.0
    assert diag.selected_sampling_algorithm in {"area_mean", "previous_colour_hold", "peak_luma"}
    assert diag.neutral_white_coverage > 0.5


def test_bright_coloured_glow_on_dark_background() -> None:
    patch = np.full((80, 120, 3), np.array([8, 8, 12], dtype=np.uint8), dtype=np.uint8)
    yy, xx = np.indices((80, 120))
    cx, cy = 60, 40
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    glow = np.clip(1.0 - (dist / 35.0), 0.0, 1.0)
    patch[:, :, 0] = np.clip(8 + (220 * glow), 0, 255).astype(np.uint8)
    patch[:, :, 1] = np.clip(8 + (40 * glow), 0, 255).astype(np.uint8)
    patch[:, :, 2] = np.clip(12 + (20 * glow), 0, 255).astype(np.uint8)
    color, diag = _sample_patch(patch)
    assert int(color[0]) > int(color[1]) + 20
    assert diag.selected_sampling_algorithm in {
        "saturated_highlight",
        "dominant_saturated_hue",
        "peak_luma",
    }


def test_mixed_red_blue_regions_are_stable() -> None:
    patch = np.zeros((80, 120, 3), dtype=np.uint8)
    patch[:, :60, 0] = 220
    patch[:, 60:, 2] = 220
    first, first_diag = _sample_patch(patch)
    second, second_diag = _sample_patch(
        patch,
        prev_state=ZonePaletteTemporalState(
            selected_algorithm=first_diag.selected_sampling_algorithm,
            selected_rgb=(int(first[0]), int(first[1]), int(first[2])),
            held_rgb=(float(first[0]), float(first[1]), float(first[2])),
            dominant_hue_degrees=float(first_diag.dominant_hue_degrees),
            selected_confidence=float(first_diag.candidate_confidence),
        ),
    )
    assert first_diag.selected_sampling_algorithm == second_diag.selected_sampling_algorithm
    assert int(np.max(np.abs(first.astype(np.int32) - second.astype(np.int32)))) <= 3


def test_low_light_dark_scene_does_not_amplify_noise() -> None:
    patch = np.full((80, 120, 3), np.array([18, 19, 17], dtype=np.uint8), dtype=np.uint8)
    patch[20:24, 40:44, 0] = 28
    patch[50:53, 70:73, 2] = 26
    color, diag = _sample_patch(patch)
    assert int(np.max(color)) < 32
    assert diag.fallback_reason in {"low_light", "maintain", "initial"}
    assert diag.selected_sampling_algorithm == "area_mean"


def test_frame_sequence_does_not_flip_algorithm_every_frame() -> None:
    patch = _green_with_white_text_patch()
    prev_state = None
    algos: list[str] = []
    for _ in range(6):
        color, diag, prev_state, _merged = palette_adaptive_zone_color(patch, prev_state=prev_state)
        algos.append(diag.selected_sampling_algorithm)
    assert len(set(algos)) <= 2


def test_palette_adaptive_zone_colors_integration() -> None:
    frame = np.full((100, 160, 3), np.array([40, 180, 60], dtype=np.uint8), dtype=np.uint8)
    frame[20:80, 30:130, :] = np.array([255, 255, 255], dtype=np.uint8)
    zones_px = [(0, 0, 160, 100)]
    colors, meta = zone_colors_array_with_meta(
        frame, zones_px, sampling_mode=SAMPLING_MODE_PALETTE_ADAPTIVE, mode="balanced"
    )
    assert int(colors[0][1]) > int(colors[0][0])
    assert meta.per_zone_palette_diagnostics[0]["selected_sampling_algorithm"]


def test_effective_sampling_mode_ambient_defaults_to_palette_adaptive() -> None:
    assert (
        effective_sampling_mode(
            sampling_mode="auto",
            color_style="ambient",
            accuracy_mode=False,
        )
        == SAMPLING_MODE_PALETTE_ADAPTIVE
    )


def test_palette_adaptive_green_sidebar_avoids_white_washout() -> None:
    frame = np.full((100, 160, 3), np.array([50, 190, 70], dtype=np.uint8), dtype=np.uint8)
    frame[15:85, 25:135, :] = np.array([255, 255, 255], dtype=np.uint8)
    zones_px = [(0, 0, 160, 100)]
    palette = zone_colors_array(frame, zones_px, sampling_mode=SAMPLING_MODE_PALETTE_ADAPTIVE)
    area = zone_colors_array(frame, zones_px, sampling_mode="area_average", mode="balanced")
    palette_mean = float(np.mean(palette[0]))
    area_mean = float(np.mean(area[0]))
    assert palette_mean < 220.0
    assert int(palette[0][1]) > int(palette[0][0])
    assert int(palette[0][1]) > int(area[0][1]) - 5
    assert palette_mean <= area_mean + 5.0
