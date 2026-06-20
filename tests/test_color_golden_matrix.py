"""Golden swatch matrix through the full color pipeline."""

from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SYNC_MODE_4D
from nanoleaf_sync.runtime.color_accuracy_diagnostics import (
    GOLDEN_SWATCH_SAMPLES,
    run_color_accuracy_diagnostic,
    validate_golden_swatch_bounds,
)
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.color_processing import apply_color_style_mapping
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def _full_pipeline_mapper(*, sync_mode: str = SYNC_MODE_4D, color_style: str = "reference"):
    width, height = 120, 80
    zones_px = zones_from_config(
        make_edge_weighted_zones(1, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )

    def mapper(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        raw = np.asarray([rgb], dtype=np.uint8)
        params = ColorPipelineParams(
            sync_mode=sync_mode,
            color_style=color_style,
            accuracy_mode=True,
            light_spread="precise",
            motion_preset="responsive",
            smoothing=0.35,
            return_diagnostics=False,
        )
        out = process_zone_colors(
            frame=None,
            precomputed_zone_colors=raw,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=[0],
            params=params,
        )
        row = out[0]
        return (int(row[0]), int(row[1]), int(row[2]))

    return mapper


def test_style_mapping_golden_bounds() -> None:
    result = run_color_accuracy_diagnostic(
        mapper=_full_pipeline_mapper(color_style="reference"),
        color_style="reference",
    )
    violations = validate_golden_swatch_bounds(result.entries)
    assert not violations, "; ".join(violations)


def test_reference_style_only_golden_greys_and_primaries() -> None:
    for name, rgb in GOLDEN_SWATCH_SAMPLES.items():
        mapped = apply_color_style_mapping(
            np.asarray([rgb], dtype=np.float32), color_style="reference"
        )[0]
        spread = int(np.max(mapped) - np.min(mapped))
        if name in {"grey_16", "grey_64", "grey_128", "grey_196", "white"}:
            assert spread <= 2, f"{name} spread={spread}"
        elif name in {"red", "green", "blue", "cyan", "magenta", "yellow"}:
            assert float(np.max(mapped)) > 10.0, f"{name} collapsed to black"


def _hdr_pipeline_mapper(*, color_style: str = "reference"):
    width, height = 120, 80
    zones_px = zones_from_config(
        make_edge_weighted_zones(1, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )

    def mapper(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        raw = np.asarray([rgb], dtype=np.uint8)
        params = ColorPipelineParams(
            sync_mode=SYNC_MODE_4D,
            color_style=color_style,
            accuracy_mode=True,
            compositor_hdr_mode=True,
            sdr_boost_nits=203.0,
            light_spread="precise",
            motion_preset="responsive",
            smoothing=0.35,
            return_diagnostics=False,
        )
        out = process_zone_colors(
            frame=None,
            precomputed_zone_colors=raw,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=[0],
            params=params,
        )
        row = out[0]
        return (int(row[0]), int(row[1]), int(row[2]))

    return mapper


def test_hdr_compositor_golden_neutrals_and_primaries() -> None:
    mapper = _hdr_pipeline_mapper(color_style="reference")
    for name, rgb in GOLDEN_SWATCH_SAMPLES.items():
        r, g, b = mapper(rgb)
        spread = max(r, g, b) - min(r, g, b)
        if name in {"grey_16", "grey_64", "grey_128", "grey_196", "white"}:
            assert spread <= 8, f"{name} spread={spread}"
        elif name == "grey_blue_low_sat":
            assert spread <= 12, f"{name} spread={spread}"
        elif name in {"red", "green", "blue", "cyan", "magenta", "yellow"}:
            assert max(r, g, b) > 10, f"{name} collapsed to black"
            peak = max(r, g, b)
            assert peak <= 255, f"{name} clipped unexpectedly"
            if name == "red":
                assert r == peak and r > g + 15 and r > b + 15
            elif name == "green":
                assert g == peak and g > r + 15 and g > b + 15
            elif name == "blue":
                assert b == peak and b > r + 15 and b > g + 15


def test_hdr_compositor_neutral_greys_stay_balanced() -> None:
    mapper = _hdr_pipeline_mapper(color_style="reference")
    for grey in ((64, 64, 64), (128, 128, 128), (196, 196, 196)):
        r, g, b = mapper(grey)
        assert abs(r - g) <= 8
        assert abs(g - b) <= 8
        assert max(r, g, b) > 0
