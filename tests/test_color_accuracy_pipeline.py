from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.color_processing import apply_color_style_mapping, color_pipeline_diagnostics
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def _map_single(rgb: tuple[int, int, int], style: str) -> dict[str, float | bool | tuple[int, int, int]]:
    out = apply_color_style_mapping(np.asarray([rgb], dtype=np.float32), color_style=style)[0]
    return color_pipeline_diagnostics(input_rgb=rgb, output_rgb=tuple(int(v) for v in out.tolist()))


def test_reference_style_limits_chroma_growth_and_preserves_neutral() -> None:
    red = _map_single((220, 50, 45), "reference")
    grey = _map_single((128, 128, 128), "reference")
    assert float(red["chroma_ratio"]) <= 1.05
    assert bool(grey["neutral_grey_preserved"]) is True


def test_medium_grey_edge_produces_visible_neutral_output() -> None:
    width, height, zone_count = 240, 140, 24
    zones_px = zones_from_config(make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="balanced"), width, height)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:10, :, :] = 128

    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        brightness=1.0,
        smoothing=1.0,
        edge_locality="balanced",
        motion_preset="responsive",
        color_style="ambient",
        compositor_hdr_mode=True,
        sdr_boost_nits=200.0,
        hdr_max_nits=1000.0,
    )
    arr = np.asarray(colors, dtype=np.uint8)
    assert int(arr[:, 0].mean()) > 10
    assert abs(float(arr[:, 0].mean()) - float(arr[:, 1].mean())) < 8.0
    assert abs(float(arr[:, 1].mean()) - float(arr[:, 2].mean())) < 8.0


def test_vivid_and_punchy_allow_more_chroma_than_reference() -> None:
    reference = _map_single((45, 95, 225), "reference")
    vivid = _map_single((45, 95, 225), "vivid")
    punchy = _map_single((45, 95, 225), "punchy")
    assert float(vivid["chroma_ratio"]) >= float(reference["chroma_ratio"])
    assert float(punchy["chroma_ratio"]) >= float(vivid["chroma_ratio"])


def test_natural_style_chroma_ratio_caps_at_105() -> None:
    saturated = _map_single((235, 80, 40), "natural")
    assert float(saturated["chroma_ratio"]) <= 1.05
