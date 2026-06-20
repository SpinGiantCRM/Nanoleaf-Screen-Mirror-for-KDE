from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SYNC_MODE_4D
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def _run_pipeline(
    *,
    frame: np.ndarray,
    prev_smoothed_colors: list[tuple[int, int, int]],
    staleness_ms: float,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]], np.ndarray]:
    width, height, zone_count = 120, 80, 8
    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )
    params = ColorPipelineParams(
        sync_mode=SYNC_MODE_4D,
        predictive_sync_strength=0.6,
        effective_target_fps=60.0,
        config_fps=120.0,
        staleness_ms=staleness_ms,
        motion_preset="dynamic",
        smoothing=0.35,
        color_style="natural",
        return_diagnostics=True,
    )
    out, _sampled, _pre, final, _timings, history = process_zone_colors(
        frame=frame,
        precomputed_zone_colors=None,
        prev_smoothed_colors=prev_smoothed_colors,
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        params=params,
    )
    return out, history, final


def test_pipeline_history_matches_sent_output() -> None:
    frame = np.full((80, 120, 3), 120, dtype=np.uint8)
    prev = [(100.0, 100.0, 100.0)] * 8
    out, history, final = _run_pipeline(
        frame=frame,
        prev_smoothed_colors=prev,
        staleness_ms=16.0,
    )
    out_arr = np.asarray(out, dtype=np.float32)
    history_arr = np.asarray(history, dtype=np.float32)
    assert float(np.max(np.abs(out_arr - np.rint(history_arr)))) <= 1.0
    assert float(np.max(out_arr)) <= float(np.max(final)) + 1.0


def test_dark_grey_frame_zones_stay_neutral_in_pipeline() -> None:
    frame = np.full((80, 120, 3), 14, dtype=np.uint8)
    frame[10:20, 10:30, :] = np.array([16, 12, 15], dtype=np.uint8)
    frame[30:40, 40:60, :] = np.array([13, 15, 12], dtype=np.uint8)
    prev: list[tuple[int, int, int]] = [(8, 8, 8)] * 8
    out, _history, final = _run_pipeline(
        frame=frame,
        prev_smoothed_colors=prev,
        staleness_ms=8.0,
    )
    arr = np.asarray(final, dtype=np.int32)
    spread = np.max(arr, axis=1) - np.min(arr, axis=1)
    assert int(np.max(spread)) <= 8
    assert int(np.max(arr[:, 1]) - np.min(arr[:, 0])) <= 6


def test_black_frame_output_is_fully_off() -> None:
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    prev: list[tuple[float, float, float]] = [(200.0, 200.0, 200.0)] * 8
    out, history, final = _run_pipeline(
        frame=frame,
        prev_smoothed_colors=prev,
        staleness_ms=16.0,
    )
    assert int(np.max(np.asarray(out, dtype=np.float32))) == 0
    assert int(np.max(final)) == 0


def test_static_scene_converges_without_oscillation() -> None:
    frame = np.full((80, 120, 3), 128, dtype=np.uint8)
    prev: list[tuple[int, int, int]] = []
    outputs: list[float] = []
    for _ in range(6):
        out, history, _final = _run_pipeline(
            frame=frame,
            prev_smoothed_colors=prev,
            staleness_ms=16.0,
        )
        outputs.append(float(np.mean(np.asarray(out, dtype=np.float32))))
        prev = history
    tail = outputs[-3:]
    assert max(tail) - min(tail) <= 2.0
