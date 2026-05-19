from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, LedCalibrationProfile
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
    color_pipeline_diagnostics,
)
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def test_calibration_reset_defaults_are_stable() -> None:
    defaults = LedCalibrationProfile()
    assert defaults.red_gain == 1.0
    assert defaults.green_gain == 1.0
    assert defaults.blue_gain == 1.0
    assert defaults.led_gamma == 1.0
    assert defaults.white_balance_temperature == 0.0
    assert defaults.chroma_compression == 0.0
    assert defaults.neutral_luminance_gain == 1.0


def test_black_and_dark_grey_behavior_with_led_black_cutoff() -> None:
    black = apply_led_calibration(
        np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        LedCalibration(black_luminance_cutoff=0.004, black_luminance_knee=0.002),
    )[0]
    dark = apply_led_calibration(
        np.asarray([[20.0, 20.0, 20.0]], dtype=np.float32),
        LedCalibration(black_luminance_cutoff=0.004, black_luminance_knee=0.002),
    )[0]
    assert int(np.max(np.rint(black))) <= 1
    assert int(np.max(np.rint(dark))) >= 2


def test_medium_grey_and_white_are_neutral_and_visible() -> None:
    medium = apply_led_calibration(
        np.asarray([[128.0, 128.0, 128.0]], dtype=np.float32), LedCalibration()
    )[0]
    white = apply_led_calibration(
        np.asarray([[255.0, 255.0, 255.0]], dtype=np.float32), LedCalibration()
    )[0]
    assert int(np.max(np.abs(np.rint(medium).astype(int) - int(np.rint(medium[1]))))) <= 2
    assert int(np.min(np.rint(white))) >= 180


def test_rgb_gains_and_white_balance_controls_channels_without_grey_breakage() -> None:
    tinted = apply_led_calibration(
        np.asarray([[120.0, 120.0, 120.0]], dtype=np.float32),
        LedCalibration(red_gain=1.1, green_gain=1.0, blue_gain=0.9, white_balance_temperature=0.1),
    )[0]
    neutral = apply_led_calibration(
        np.asarray([[120.0, 120.0, 120.0]], dtype=np.float32),
        LedCalibration(red_gain=1.0, green_gain=1.0, blue_gain=1.0, white_balance_temperature=0.0),
    )[0]
    assert float(tinted[0]) > float(tinted[2])
    assert int(np.max(np.abs(np.rint(neutral).astype(int) - int(np.rint(neutral[1]))))) <= 2


def test_reference_chroma_and_low_saturation_remain_controlled() -> None:
    saturated, _ = apply_color_style_mapping_with_diagnostics(
        np.asarray([(235, 80, 40)], dtype=np.float32), color_style="reference"
    )
    sat_diag = color_pipeline_diagnostics(
        input_rgb=(235, 80, 40),
        output_rgb=tuple(int(v) for v in saturated[0].tolist()),
        color_style="reference",
    )
    muted, _ = apply_color_style_mapping_with_diagnostics(
        np.asarray([(108, 116, 126)], dtype=np.float32), color_style="reference"
    )
    muted_diag = color_pipeline_diagnostics(
        input_rgb=(108, 116, 126),
        output_rgb=tuple(int(v) for v in muted[0].tolist()),
        color_style="reference",
    )
    assert float(sat_diag["chroma_ratio"]) <= 1.05
    assert float(muted_diag["output_chroma"]) <= float(muted_diag["input_chroma"]) * 1.05


def test_local_edge_patterns_stay_local() -> None:
    width, height, zone_count = 320, 180, 20
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :40, :] = np.array([0, 255, 0], dtype=np.uint8)
    frame[:, -40:, :] = np.array([0, 0, 255], dtype=np.uint8)
    zones = make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight")
    zones_px = zones_from_config(zones, width, height)
    idx = np.arange(zone_count, dtype=np.intp)
    out = np.asarray(
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
    sat = np.max(out, axis=1) - np.min(out, axis=1)
    assert int(np.sum(sat > 60)) <= 14


def test_calibration_profiles_save_and_load(tmp_path) -> None:
    path = tmp_path / "config.toml"
    cfg = AppConfig(
        display_preset="sdr",
        led_calibration_profile_sdr=LedCalibrationProfile(
            red_gain=1.1, blue_gain=0.9, black_luminance_cutoff=0.004
        ),
        led_calibration_profile_hdr=LedCalibrationProfile(
            red_gain=1.0, blue_gain=1.0, black_luminance_cutoff=0.0032
        ),
    )
    manager = ConfigManager(path)
    manager.save(cfg)
    loaded = manager.load()
    assert loaded.led_calibration_profile_sdr.red_gain == 1.1
    assert loaded.led_calibration_profile_sdr.blue_gain == 0.9
    assert loaded.led_calibration_profile_sdr.black_luminance_cutoff == 0.004
