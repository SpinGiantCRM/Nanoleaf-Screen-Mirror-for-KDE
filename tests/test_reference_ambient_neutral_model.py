from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.color_processing import (
    apply_color_style_mapping,
    color_pipeline_diagnostics,
)
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def _diag(
    rgb: tuple[int, int, int], style: str
) -> dict[str, float | bool | tuple[int, int, int] | str]:
    out = apply_color_style_mapping(np.asarray([rgb], dtype=np.float32), color_style=style)[0]
    return color_pipeline_diagnostics(
        input_rgb=rgb, output_rgb=tuple(int(v) for v in out.tolist()), color_style=style
    )


def test_black_input_outputs_near_off_reference() -> None:
    d = _diag((0, 0, 0), "reference")
    assert float(d["output_lightness"]) <= 0.01
    assert bool(d["black_cutoff_applied"]) is True


def test_near_black_outputs_dim_and_stable_without_flicker() -> None:
    seq = [(2, 2, 2), (3, 3, 3), (2, 2, 2), (4, 4, 4), (3, 3, 3), (2, 2, 2)] * 3
    outs = [
        apply_color_style_mapping(np.asarray([rgb], dtype=np.float32), color_style="reference")[0][
            0
        ]
        for rgb in seq
    ]
    offish = [int(np.max(x)) <= 2 for x in outs]
    transitions = sum(1 for i in range(1, len(offish)) if offish[i] != offish[i - 1])
    assert transitions <= 4


def test_dark_medium_and_white_greys_stay_neutral() -> None:
    for rgb, min_l in [((20, 20, 20), 0.03), ((120, 120, 120), 0.30), ((255, 255, 255), 0.80)]:
        d = _diag(rgb, "reference")
        assert str(d["grey_neutrality_verdict"]) == "pass"
        assert float(d["output_lightness"]) >= min_l


def test_low_saturation_grey_blue_is_lightly_tinted_with_luminance_preserved() -> None:
    d = _diag((108, 116, 126), "reference")
    assert float(d["output_chroma"]) <= float(d["input_chroma"]) * 1.05
    assert abs(float(d["output_lightness"]) - float(d["input_lightness"])) <= 0.08


def test_reference_chroma_growth_is_bounded_to_105() -> None:
    d = _diag((235, 80, 40), "reference")
    assert float(d["chroma_ratio"]) <= 1.05


def test_ambient_is_brighter_than_reference_for_neutrals_without_saturation_boost() -> None:
    ref = _diag((96, 96, 96), "reference")
    amb = _diag((96, 96, 96), "ambient")
    assert float(amb["output_lightness"]) >= float(ref["output_lightness"])
    assert float(amb["output_chroma"]) <= 0.02


def test_vivid_and_punchy_can_remain_more_stylised() -> None:
    ref = _diag((45, 95, 225), "reference")
    vivid = _diag((45, 95, 225), "vivid")
    punchy = _diag((45, 95, 225), "punchy")
    assert float(vivid["chroma_ratio"]) >= float(ref["chroma_ratio"])
    assert float(punchy["chroma_ratio"]) >= float(vivid["chroma_ratio"])


def test_noisy_grey_sequence_remains_stable() -> None:
    seq = [(100, 100, 100), (102, 102, 102), (101, 101, 101), (103, 103, 103)] * 5
    outs = [
        apply_color_style_mapping(np.asarray([rgb], dtype=np.float32), color_style="ambient")[0][0]
        for rgb in seq
    ]
    per_step_delta = [
        int(np.max(np.abs(outs[i].astype(int) - outs[i - 1].astype(int))))
        for i in range(1, len(outs))
    ]
    assert max(per_step_delta) <= 6


def test_black_to_white_transition_remains_prompt() -> None:
    black = apply_color_style_mapping(
        np.asarray([(0, 0, 0)], dtype=np.float32), color_style="reference"
    )[0][0]
    white = apply_color_style_mapping(
        np.asarray([(255, 255, 255)], dtype=np.float32), color_style="reference"
    )[0][0]
    assert int(np.max(black)) <= 1
    assert int(np.min(white)) >= 180


def test_desaturated_scene_regression_reference_and_ambient() -> None:
    width, height, zone_count = 320, 180, 20
    frame = np.full((height, width, 3), 112, dtype=np.uint8)  # grey road/background
    frame[20:90, 25:95, :] = np.array([92, 116, 90], dtype=np.uint8)  # muted green tree
    frame[10:95, 130:300, :] = np.array([190, 190, 190], dtype=np.uint8)  # white/grey buildings
    frame[35:50, 150:165, :] = np.array([220, 40, 40], dtype=np.uint8)  # small coloured UI patch
    frame[70:84, 260:276, :] = np.array([40, 120, 230], dtype=np.uint8)  # small coloured object
    frame[:12, :, :] = np.array([15, 15, 15], dtype=np.uint8)  # dark UI bar
    frame[-12:, :, :] = np.array([18, 18, 18], dtype=np.uint8)

    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )
    idx = np.arange(zone_count, dtype=np.intp)

    ref = np.asarray(
        process_frame(
            frame=frame,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=idx,
            brightness=1.0,
            smoothing=1.0,
            edge_locality="tight",
            motion_preset="responsive",
            color_style="reference",
            light_spread="precise",
        ),
        dtype=np.uint8,
    )
    amb = np.asarray(
        process_frame(
            frame=frame,
            prev_smoothed_colors=[],
            zones_px=zones_px,
            device_zone_indices=idx,
            brightness=1.0,
            smoothing=1.0,
            edge_locality="tight",
            motion_preset="responsive",
            color_style="ambient",
            light_spread="precise",
        ),
        dtype=np.uint8,
    )

    # Neutral zones are neutral in reference.
    neutral_delta = np.abs(ref[:, 0].astype(int) - ref[:, 1].astype(int)) + np.abs(
        ref[:, 1].astype(int) - ref[:, 2].astype(int)
    )
    assert int(np.median(neutral_delta)) <= 12

    # Small coloured patches stay local (do not saturate whole strip).
    sat = np.max(ref, axis=1) - np.min(ref, axis=1)
    assert int(np.sum(sat > 70)) <= 6

    # Ambient is slightly brighter for mostly neutral scene, still controlled.
    assert float(np.mean(amb)) >= float(np.mean(ref))
    amb_sat = np.max(amb, axis=1) - np.min(amb, axis=1)
    assert float(np.mean(amb_sat)) <= 50.0
