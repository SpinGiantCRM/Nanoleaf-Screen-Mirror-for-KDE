from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
    color_pipeline_diagnostics,
)
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def test_led_calibration_gains_apply_per_channel() -> None:
    arr = np.asarray([[100.0, 100.0, 100.0]], dtype=np.float32)
    out = apply_led_calibration(arr, LedCalibration(red_gain=1.2, green_gain=1.0, blue_gain=0.8))
    assert out.shape == arr.shape
    assert float(out[0, 0]) > float(out[0, 1])
    assert float(out[0, 2]) < float(out[0, 1])


def test_chroma_compression_reduces_oversaturation() -> None:
    src = np.asarray([[240.0, 90.0, 40.0]], dtype=np.float32)
    low = apply_led_calibration(src, LedCalibration(chroma_compression=0.0))[0]
    high = apply_led_calibration(src, LedCalibration(chroma_compression=0.35))[0]
    low_diag = color_pipeline_diagnostics(
        input_rgb=(240, 90, 40), output_rgb=tuple(int(v) for v in np.rint(low))
    )
    high_diag = color_pipeline_diagnostics(
        input_rgb=(240, 90, 40), output_rgb=tuple(int(v) for v in np.rint(high))
    )
    assert float(high_diag["output_chroma"]) <= float(low_diag["output_chroma"])


def test_reference_natural_chroma_is_bounded() -> None:
    for style in ("reference", "natural"):
        styled, _ = apply_color_style_mapping_with_diagnostics(
            np.asarray([(235, 80, 40)], dtype=np.float32), color_style=style
        )
        diag = color_pipeline_diagnostics(
            input_rgb=(235, 80, 40), output_rgb=tuple(int(v) for v in styled[0].tolist())
        )
        assert float(diag["chroma_ratio"]) <= 1.05


def test_low_saturation_colour_stays_low_saturation() -> None:
    styled, _ = apply_color_style_mapping_with_diagnostics(
        np.asarray([(118, 122, 128)], dtype=np.float32), color_style="natural"
    )
    diag = color_pipeline_diagnostics(
        input_rgb=(118, 122, 128), output_rgb=tuple(int(v) for v in styled[0].tolist())
    )
    assert float(diag["output_chroma"]) <= float(diag["input_chroma"]) * 1.05


def test_light_spread_precise_preserves_zone_variance() -> None:
    width, height, zone_count = 640, 360, 20
    frame = np.full((height, width, 3), 70, dtype=np.uint8)
    frame[:, :80, :] = np.array([220, 30, 220], dtype=np.uint8)
    frame[height - 90 :, :100, :] = np.array([20, 220, 40], dtype=np.uint8)
    zones = make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight")
    zones_px = zones_from_config(zones, width, height)
    idx = np.arange(zone_count, dtype=np.intp)
    precise = np.asarray(
        process_frame(
            frame=frame,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=idx,
            brightness=1.0,
            smoothing=1.0,
            color_style="reference",
            edge_locality="tight",
            light_spread="precise",
        ),
        dtype=np.float32,
    )
    soft = np.asarray(
        process_frame(
            frame=frame,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=idx,
            brightness=1.0,
            smoothing=1.0,
            color_style="reference",
            edge_locality="tight",
            light_spread="soft",
        ),
        dtype=np.float32,
    )
    assert float(np.var(precise)) >= float(np.var(soft))
