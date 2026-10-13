"""Deterministic whole-frame reference sequences; broken old dither disabled for parity."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map
from nanoleaf_sync.runtime.color_pipeline import (
    build_pipeline_params_from_config,
    process_zone_colors,
    zone_sample_motion,
)
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.zone_presets import edge_side_counts, make_edge_weighted_zones

rng = np.random.default_rng(719)
cases = []
blob = bytearray()
offsets = {}
w, h = 96, 64
variants = [
    (style, quality, "auto", True, "balanced")
    for style in ("reference", "ambient", "vivid", "punchy")
    for quality in ("high", "balanced")
]
variants += [
    ("ambient", quality, mode, False, locality)
    for quality in ("high", "balanced")
    for mode in ("area_average", "edge_direct")
    for locality in ("tight", "balanced", "wide")
]
for style, quality, sampling, box_filter, locality in variants:
    config = AppConfig(
        color_style=style,
        sampling_quality=quality,
        sampling_mode=sampling,
        zone_box_filter_sampling=box_filter,
        edge_locality=locality,
        blue_noise_dither=False,
        device_zone_count=48,
    )
    config.calibration.device_zone_count = 48
    anchors = (2, 17, 26, 41)
    keys = ("top_left", "top_right", "bottom_right", "bottom_left")
    for key, value in zip(keys, anchors, strict=True):
        setattr(config.calibration, "corner_anchor_" + key, value)
    if quality == "balanced":
        config.privacy_zones = [PrivacyZone(x=0.15, y=0.2, w=0.3, h=0.4)]
    zones = zones_from_config(
        make_edge_weighted_zones(48, width=w, height=h, edge_locality=locality), w, h
    )
    mapping = derive_anchor_zone_map(
        zone_count=48,
        device_zone_count=48,
        anchors=dict(zip(keys, anchors, strict=True)),
        source_side_counts=edge_side_counts(zone_count=48, width=w, height=h),
    ).mapping
    params = replace(
        build_pipeline_params_from_config(
            config, capture_display_referred=True, skip_display_gamut_adaptation=True
        ),
        compositor_hdr_mode=False,
    )
    process_zone_colors._zone_accumulator = None
    history = []
    frames = []
    for index in range(24):
        frame = np.full((h, w, 3), (25, 170, 45), dtype=np.uint8)
        if index % 8 == 1:
            frame[: h // 2] = 255
        elif index % 8 == 2:
            frame[:] = rng.integers(0, 32, frame.shape, dtype=np.uint8)
        elif index % 8 == 3:
            frame[:] = rng.integers(0, 256, frame.shape, dtype=np.uint8)
        elif index % 8 == 4:
            frame[:] = 128
        elif index % 8 == 5:
            frame[:] = 0
        elif index % 8 == 6:
            frame[:] = (210, 20, 25)
        elif index % 8 == 7:
            frame[: h // 8] = 0
            frame[-h // 8 :] = 0
        colors, raw, _, _, times, smooth, sent = process_zone_colors(
            frame=frame,
            precomputed_zone_colors=None,
            prev_smoothed_colors=history,
            zones_px=zones,
            device_zone_indices=mapping,
            params=replace(params, return_diagnostics=True),
        )
        data = frame.tobytes()
        if data not in offsets:
            offsets[data] = len(blob)
            blob.extend(data)
        frames.append(dict(offset=offsets[data], sampled=raw.tolist(), colors=colors))
        samples = [tuple(int(c) for c in row) for row in raw.tolist()]
        params = replace(
            params,
            palette_frame_index=index + 1,
            prev_sampled_zone_colors=samples,
            previous_palette_algorithms=times.per_zone_sampling_mode,
            zone_palette_temporal_states=times.per_zone_palette_temporal_states,
            prev_smooth_float_colors=smooth,
            prev_sent_colors=sent,
            prior_zone_sample_motion=zone_sample_motion(
                raw, params.prev_sampled_zone_colors or None
            ),
            prior_area_average_mode=times.area_average_active,
            sampling_mode_dwell_remaining=times.sampling_mode_dwell_remaining,
            dark_zone_stabilize_hold=times.dark_zone_stabilize_hold,
            blend_hysteresis=times.blend_hysteresis,
            output_quantization_prev_hold=times.output_quantization_prev_hold,
        )
        history = colors
    cases.append(
        dict(
            style=style,
            quality=quality,
            sampling=sampling,
            box_filter=box_filter,
            locality=locality,
            anchors=anchors,
            width=w,
            height=h,
            frames=frames,
        )
    )
Path(__file__).resolve().parents[1].joinpath("fixtures/pipeline.json").write_text(
    json.dumps(cases, separators=(",", ":")) + "\n"
)

Path(__file__).resolve().parents[1].joinpath("fixtures/pipeline-rgb.bin").write_bytes(blob)
