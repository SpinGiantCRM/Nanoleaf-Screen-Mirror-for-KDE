from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SYNC_MODE_4D
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def _run_full_pipeline(
    *,
    raw_zone_rgb: np.ndarray,
    prev_smoothed: list[tuple[float, float, float]] | list[tuple[int, int, int]],
    staleness_ms: float = 8.0,
    color_style: str = "reference",
    accuracy_mode: bool = True,
) -> tuple[list[tuple[int, int, int]], list[tuple[float, float, float]]]:
    width, height, zone_count = 120, 80, int(raw_zone_rgb.shape[0])
    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )
    params = ColorPipelineParams(
        sync_mode=SYNC_MODE_4D,
        color_style=color_style,
        accuracy_mode=accuracy_mode,
        predictive_sync_strength=0.6,
        effective_target_fps=60.0,
        config_fps=120.0,
        staleness_ms=staleness_ms,
        motion_preset="responsive",
        smoothing=0.35,
        light_spread="precise",
        return_diagnostics=True,
    )
    out, _sampled, _pre, _final, _timings, history = process_zone_colors(
        frame=None,
        precomputed_zone_colors=raw_zone_rgb.astype(np.uint8),
        prev_smoothed_colors=prev_smoothed,
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        params=params,
    )
    return out, history  # type: ignore[return-value]


def test_noisy_dark_sequence_limited_level_transitions() -> None:
    seq = [
        np.full((8, 3), rgb, dtype=np.uint8)
        for rgb in (
            (4, 5, 3),
            (6, 4, 5),
            (3, 6, 4),
            (7, 5, 4),
            (4, 4, 6),
            (5, 7, 3),
            (6, 3, 5),
            (4, 6, 4),
            (5, 4, 5),
            (3, 5, 4),
        )
    ]
    prev: list[tuple[float, float, float]] = [(2.0, 2.0, 2.0)] * 8
    level_changes = 0
    last_levels: list[int] | None = None
    for frame in seq:
        out, history = _run_full_pipeline(raw_zone_rgb=frame, prev_smoothed=prev)
        levels = [int(round(float(np.max(row)))) for row in np.asarray(out, dtype=np.float32)]
        if last_levels is not None:
            level_changes += sum(
                1 for a, b in zip(last_levels, levels, strict=True) if abs(a - b) > 1
            )
        last_levels = levels
        prev = history
    assert level_changes <= 8


def test_history_aligns_with_sent_output() -> None:
    raw = np.full((8, 3), 14, dtype=np.uint8)
    prev = [(12.0, 12.0, 12.0)] * 8
    out, history = _run_full_pipeline(raw_zone_rgb=raw, prev_smoothed=prev)
    out_arr = np.asarray(out, dtype=np.float32)
    hist_arr = np.asarray(history, dtype=np.float32)
    assert float(np.max(np.abs(out_arr - np.rint(hist_arr)))) <= 1.0


def test_alternating_dark_grey_does_not_flip_off_and_green() -> None:
    a = np.full((8, 3), 3, dtype=np.uint8)
    b = np.full((8, 3), 7, dtype=np.uint8)
    prev: list[tuple[float, float, float]] = [(5.0, 5.0, 5.0)] * 8
    outputs: list[np.ndarray] = []
    for frame in (a, b, a, b, a, b):
        out, history = _run_full_pipeline(raw_zone_rgb=frame, prev_smoothed=prev)
        outputs.append(np.asarray(out, dtype=np.int32))
        prev = history
    for arr in outputs:
        spread = np.max(arr, axis=1) - np.min(arr, axis=1)
        assert int(np.max(spread)) <= 4
        assert int(np.max(arr[:, 1]) - np.min(arr[:, 0])) <= 4
    peak_a = float(np.mean(outputs[0]))
    peak_b = float(np.mean(outputs[1]))
    assert abs(peak_a - peak_b) <= 6.0


def test_temporal_smoothing_runs_before_dark_output(monkeypatch) -> None:
    call_order: list[str] = []

    import nanoleaf_sync.runtime.color_pipeline as pipeline_mod

    original_blend = pipeline_mod.adaptive_one_euro_blend
    original_dark = pipeline_mod.apply_dark_zone_output

    def tracked_blend(**kwargs):
        call_order.append("temporal")
        return original_blend(**kwargs)

    def tracked_dark(colors, *args, **kwargs):
        call_order.append("dark")
        return original_dark(colors, *args, **kwargs)

    monkeypatch.setattr(pipeline_mod, "adaptive_one_euro_blend", tracked_blend)
    monkeypatch.setattr(pipeline_mod, "apply_dark_zone_output", tracked_dark)

    raw = np.full((8, 3), 14, dtype=np.uint8)
    prev = [(12.0, 12.0, 12.0)] * 8
    _run_full_pipeline(raw_zone_rgb=raw, prev_smoothed=prev)
    assert "temporal" in call_order
    assert "dark" in call_order
    assert call_order.index("temporal") < call_order.index("dark")


def test_ambient_dark_noisy_sequence_limited_level_transitions() -> None:
    seq = [
        np.full((8, 3), rgb, dtype=np.uint8)
        for rgb in (
            (4, 5, 3),
            (6, 4, 5),
            (3, 6, 4),
            (7, 5, 4),
            (4, 4, 6),
            (5, 7, 3),
            (6, 3, 5),
            (4, 6, 4),
            (5, 4, 5),
            (3, 5, 4),
        )
    ]
    prev: list[tuple[float, float, float]] = [(2.0, 2.0, 2.0)] * 8
    level_changes = 0
    last_levels: list[int] | None = None
    for frame in seq:
        out, history = _run_full_pipeline(
            raw_zone_rgb=frame,
            prev_smoothed=prev,
            color_style="ambient",
            accuracy_mode=False,
        )
        levels = [int(round(float(np.max(row)))) for row in np.asarray(out, dtype=np.float32)]
        if last_levels is not None:
            level_changes += sum(
                1 for a, b in zip(last_levels, levels, strict=True) if abs(a - b) > 1
            )
        last_levels = levels
        prev = history
    assert level_changes <= 10


def test_hdr_compositor_dark_grey_stays_neutral() -> None:
    raw = np.full((8, 3), 48, dtype=np.uint8)
    width, height, zone_count = 120, 80, 8
    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )
    params = ColorPipelineParams(
        sync_mode=SYNC_MODE_4D,
        color_style="reference",
        accuracy_mode=True,
        compositor_hdr_mode=True,
        sdr_boost_nits=203.0,
        smoothing=0.35,
        light_spread="precise",
        return_diagnostics=True,
    )
    out, _sampled, _pre, _final, _timings, _history = process_zone_colors(
        frame=None,
        precomputed_zone_colors=raw,
        prev_smoothed_colors=[(45.0, 45.0, 45.0)] * zone_count,
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        params=params,
    )
    arr = np.asarray(out, dtype=np.int32)
    spread = np.max(arr, axis=1) - np.min(arr, axis=1)
    assert int(np.max(spread)) <= 6
    assert int(np.max(arr)) > 0


def test_partial_bright_strip_isolates_dark_zones() -> None:
    zone_count = 24
    raw = np.zeros((zone_count, 3), dtype=np.uint8)
    raw[:8] = np.array([240, 40, 220], dtype=np.uint8)
    prev: list[tuple[float, float, float]] = [(2.0, 2.0, 2.0)] * zone_count
    out, history = _run_full_pipeline(
        raw_zone_rgb=raw,
        prev_smoothed=prev,
        color_style="ambient",
        accuracy_mode=False,
    )
    out_arr = np.asarray(out, dtype=np.float32)
    for idx in range(8):
        spread = float(np.max(out_arr[idx]) - np.min(out_arr[idx]))
        assert float(np.max(out_arr[idx])) > 40.0
        assert spread > 10.0
    for idx in range(8, zone_count):
        assert float(np.max(out_arr[idx])) < 8.0
    _ = history


def test_first_led_vivid_history_releases_to_dim_neutral() -> None:
    zone_count = 24
    raw = np.full((zone_count, 3), 28, dtype=np.uint8)
    prev: list[tuple[float, float, float]] = [(230.0, 30.0, 210.0)] * 8
    prev.extend([(28.0, 28.0, 28.0)] * (zone_count - 8))

    out, history = _run_full_pipeline(
        raw_zone_rgb=raw,
        prev_smoothed=prev,
        color_style="ambient",
        accuracy_mode=False,
    )

    out_arr = np.asarray(out, dtype=np.int32)
    hist_arr = np.asarray(history, dtype=np.float32)
    first_eight_chroma = np.max(out_arr[:8], axis=1) - np.min(out_arr[:8], axis=1)
    assert int(np.max(first_eight_chroma)) <= 6
    assert float(np.max(hist_arr[:8]) - np.min(hist_arr[:8])) <= 6.0
    assert 8.0 <= float(np.mean(out_arr[:8])) <= 40.0


def test_low_light_grey_sequence_limited_level_transitions() -> None:
    seq = [
        np.full((8, 3), rgb, dtype=np.uint8)
        for rgb in (
            (24, 25, 23),
            (26, 24, 25),
            (23, 26, 24),
            (25, 23, 26),
            (24, 26, 23),
            (26, 23, 25),
            (23, 25, 26),
            (25, 24, 24),
            (24, 23, 25),
            (26, 25, 23),
        )
    ]
    prev: list[tuple[float, float, float]] = [(24.0, 24.0, 24.0)] * 8
    level_changes = 0
    last_levels: list[int] | None = None
    for frame in seq:
        out, history = _run_full_pipeline(
            raw_zone_rgb=frame,
            prev_smoothed=prev,
            color_style="ambient",
            accuracy_mode=False,
        )
        levels = [int(round(float(np.max(row)))) for row in np.asarray(out, dtype=np.float32)]
        if last_levels is not None:
            level_changes += sum(
                1 for a, b in zip(last_levels, levels, strict=True) if abs(a - b) > 1
            )
        last_levels = levels
        prev = history
    assert level_changes <= 8
