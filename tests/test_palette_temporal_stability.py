from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.palette_adaptive import (
    palette_adaptive_zone_frame,
)
from nanoleaf_sync.runtime.palette_temporal import ZonePaletteTemporalState, stabilize_palette_zone
from nanoleaf_sync.runtime.zones import zone_colors_array


def _green_with_white_text_patch(*, white: bool) -> np.ndarray:
    patch = np.full((80, 120, 3), np.array([40, 180, 60], dtype=np.uint8), dtype=np.uint8)
    if white:
        patch[10:70, 20:100, :] = np.array([255, 255, 255], dtype=np.uint8)
    return patch


def _run_green_white_sequence(frames: int, *, white_every: int) -> list[np.ndarray]:
    state: ZonePaletteTemporalState | None = None
    colors: list[np.ndarray] = []
    for frame_idx in range(frames):
        patch = _green_with_white_text_patch(white=(frame_idx % white_every == 0))
        frame = palette_adaptive_zone_frame(patch)
        color, state, diag = stabilize_palette_zone(
            current_best_algorithm=frame.current_best_algorithm,
            current_best_confidence=frame.current_best_confidence,
            current_best_rgb=frame.current_best_rgb,
            candidate_rgbs=frame.candidate_rgbs,
            scores=frame.scores,
            dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
            neutral_white_coverage=float(frame.diagnostics.neutral_white_coverage),
            saturated_coverage=float(frame.diagnostics.saturated_coverage),
            hue_coherence=float(frame.diagnostics.hue_coherence),
            prev_state=state,
            frame_index=frame_idx,
        )
        colors.append(color)
        assert str(diag.get("selected_algorithm", ""))
    return colors


def test_white_text_flashing_over_green_stays_mostly_green() -> None:
    colors = _run_green_white_sequence(12, white_every=2)
    greens = [int(c[1]) for c in colors]
    assert min(greens) > 80
    assert float(np.std(greens)) < 35.0
    white_like = sum(1 for c in colors if float(np.mean(c)) > 210.0)
    assert white_like <= 2


def test_one_frame_highlight_does_not_switch_algorithm() -> None:
    base = np.full((60, 80, 3), np.array([30, 160, 50], dtype=np.uint8), dtype=np.uint8)
    flash = base.copy()
    flash[5:10, 10:70, :] = 255
    state: ZonePaletteTemporalState | None = None
    algos: list[str] = []
    for patch in (base, base, flash, base, base):
        frame = palette_adaptive_zone_frame(patch)
        _color, state, diag = stabilize_palette_zone(
            current_best_algorithm=frame.current_best_algorithm,
            current_best_confidence=frame.current_best_confidence,
            current_best_rgb=frame.current_best_rgb,
            candidate_rgbs=frame.candidate_rgbs,
            scores=frame.scores,
            dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
            neutral_white_coverage=float(frame.diagnostics.neutral_white_coverage),
            saturated_coverage=float(frame.diagnostics.saturated_coverage),
            hue_coherence=float(frame.diagnostics.hue_coherence),
            prev_state=state,
        )
        algos.append(str(diag["selected_algorithm"]))
    assert len(set(algos)) <= 2


def test_scene_cut_green_to_red_transitions_quickly() -> None:
    green = np.full((60, 80, 3), np.array([20, 200, 30], dtype=np.uint8), dtype=np.uint8)
    red = np.full((60, 80, 3), np.array([220, 20, 20], dtype=np.uint8), dtype=np.uint8)
    state: ZonePaletteTemporalState | None = None
    greens: list[int] = []
    reds: list[int] = []
    for idx, patch in enumerate((green, green, red, red)):
        frame = palette_adaptive_zone_frame(patch)
        color, state, diag = stabilize_palette_zone(
            current_best_algorithm=frame.current_best_algorithm,
            current_best_confidence=frame.current_best_confidence,
            current_best_rgb=frame.current_best_rgb,
            candidate_rgbs=frame.candidate_rgbs,
            scores=frame.scores,
            dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
            neutral_white_coverage=float(frame.diagnostics.neutral_white_coverage),
            saturated_coverage=float(frame.diagnostics.saturated_coverage),
            hue_coherence=float(frame.diagnostics.hue_coherence),
            prev_state=state,
            global_scene_cut=idx >= 2,
            frame_index=idx,
        )
        greens.append(int(color[1]))
        reds.append(int(color[0]))
    assert reds[-1] > 150
    assert greens[-1] < greens[0] - 40


def test_low_confidence_candidate_change_is_held() -> None:
    patch_a = np.full((60, 80, 3), np.array([40, 180, 60], dtype=np.uint8), dtype=np.uint8)
    patch_b = patch_a.copy()
    patch_b[0:8, 0:8, :] = np.array([255, 255, 255], dtype=np.uint8)
    state: ZonePaletteTemporalState | None = None
    first_frame = palette_adaptive_zone_frame(patch_a)
    color, state, _diag = stabilize_palette_zone(
        current_best_algorithm=first_frame.current_best_algorithm,
        current_best_confidence=first_frame.current_best_confidence,
        current_best_rgb=first_frame.current_best_rgb,
        candidate_rgbs=first_frame.candidate_rgbs,
        scores=first_frame.scores,
        dominant_hue_degrees=float(first_frame.diagnostics.dominant_hue_degrees),
        neutral_white_coverage=float(first_frame.diagnostics.neutral_white_coverage),
        saturated_coverage=float(first_frame.diagnostics.saturated_coverage),
        hue_coherence=float(first_frame.diagnostics.hue_coherence),
        prev_state=state,
    )
    held = color.copy()
    second_frame = palette_adaptive_zone_frame(patch_b)
    color2, _state2, diag2 = stabilize_palette_zone(
        current_best_algorithm=second_frame.current_best_algorithm,
        current_best_confidence=second_frame.current_best_confidence,
        current_best_rgb=second_frame.current_best_rgb,
        candidate_rgbs=second_frame.candidate_rgbs,
        scores=second_frame.scores,
        dominant_hue_degrees=float(second_frame.diagnostics.dominant_hue_degrees),
        neutral_white_coverage=float(second_frame.diagnostics.neutral_white_coverage),
        saturated_coverage=float(second_frame.diagnostics.saturated_coverage),
        hue_coherence=float(second_frame.diagnostics.hue_coherence),
        prev_state=state,
    )
    assert (
        bool(diag2.get("algorithm_switch_blocked"))
        or float(np.mean(np.abs(color2.astype(np.float32) - held.astype(np.float32)))) < 25.0
    )


def test_sustained_candidate_change_switches_after_dwell() -> None:
    blue = np.full((60, 80, 3), np.array([20, 40, 200], dtype=np.uint8), dtype=np.uint8)
    orange = np.full((60, 80, 3), np.array([240, 120, 10], dtype=np.uint8), dtype=np.uint8)
    state: ZonePaletteTemporalState | None = None
    reds: list[int] = []
    for idx in range(8):
        patch = orange if idx >= 2 else blue
        frame = palette_adaptive_zone_frame(patch)
        color, state, _diag = stabilize_palette_zone(
            current_best_algorithm=frame.current_best_algorithm,
            current_best_confidence=frame.current_best_confidence,
            current_best_rgb=frame.current_best_rgb,
            candidate_rgbs=frame.candidate_rgbs,
            scores=frame.scores,
            dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
            neutral_white_coverage=float(frame.diagnostics.neutral_white_coverage),
            saturated_coverage=float(frame.diagnostics.saturated_coverage),
            hue_coherence=float(frame.diagnostics.hue_coherence),
            prev_state=state,
            frame_index=idx,
        )
        reds.append(int(color[0]))
    assert reds[-1] > reds[1] + 60


def test_zone_colors_array_temporal_integration() -> None:
    frame = _green_with_white_text_patch(white=True)
    zones_px = [(0, 0, 120, 80)]
    states = [
        ZonePaletteTemporalState(
            selected_algorithm="dominant_saturated_hue",
            selected_rgb=(40, 180, 60),
            held_rgb=(40.0, 180.0, 60.0),
            dominant_hue_degrees=120.0,
            selected_confidence=1.0,
        ).to_dict()
    ]
    colors = zone_colors_array(
        frame,
        zones_px,
        sampling_mode="palette_adaptive",
        palette_temporal_states=states,
        stabilize_palette=True,
    )
    assert int(colors[0][1]) > int(colors[0][0])
