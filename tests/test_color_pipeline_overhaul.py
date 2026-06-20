from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.color.capture_metadata import resolve_capture_metadata, resolve_display_preset
from nanoleaf_sync.config.presets import effective_light_spread, is_accuracy_mode
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.compositor import apply_zone_sdr_boost, apply_zone_sdr_boost_float
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.ring_buf import SPSCRingBuffer
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones


def test_resolve_display_preset_auto_prefers_hdr_on_plasma(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanoleaf_sync.color.capture_metadata._plasma_hdr_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.capture_metadata._plasma_sdr_white_nits",
        lambda: 200.0,
    )
    resolved = resolve_display_preset(
        display_preset="auto",
        hdr_transfer="srgb",
        hdr_primaries="bt709",
        compositor_hdr_mode=False,
        sdr_boost_nits=80.0,
    )
    assert resolved.preset == "hdr"
    assert resolved.hdr_transfer == "pq"
    assert resolved.hdr_primaries == "bt2020"


def test_kwin_display_referred_metadata_skips_redundant_tone_map() -> None:
    meta = resolve_capture_metadata(
        user_transfer="pq",
        user_primaries="bt2020",
        kwin_display_referred=True,
    )
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.source == "kwin display-referred"


def test_resolve_compositor_hdr_runtime_auto_enables_from_plasma(monkeypatch) -> None:
    from nanoleaf_sync.color.capture_metadata import resolve_compositor_hdr_runtime

    monkeypatch.setattr(
        "nanoleaf_sync.color.capture_metadata._plasma_hdr_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.capture_metadata._plasma_sdr_white_nits",
        lambda: 203.0,
    )
    hdr_mode, nits = resolve_compositor_hdr_runtime(
        compositor_hdr_mode=False,
        sdr_boost_nits=80.0,
    )
    assert hdr_mode is True
    assert nits == pytest.approx(203.0)


def test_accuracy_mode_caps_light_spread() -> None:
    assert (
        effective_light_spread(
            light_spread="soft",
            accuracy_mode=True,
            color_style="reference",
        )
        == "off"
    )


def test_sdr_boost_applied_before_style_mapping_in_pipeline() -> None:
    width, height, zone_count = 120, 80, 8
    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="balanced"),
        width,
        height,
    )
    frame = np.full((height, width, 3), 200, dtype=np.uint8)
    params = ColorPipelineParams(
        compositor_hdr_mode=True,
        sdr_boost_nits=160.0,
        color_style="reference",
        return_diagnostics=True,
    )
    out = process_zone_colors(
        frame=frame,
        precomputed_zone_colors=None,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        params=params,
    )
    colors, sampled, _pre, final, _timings, _history = out  # type: ignore[misc]
    assert colors
    flat_expected = apply_zone_sdr_boost(
        sampled[0:1].astype(np.uint8),
        sdr_boost_nits=160.0,
        hdr_max_nits=1000.0,
    )[0]
    adaptive_expected = apply_zone_sdr_boost_float(
        sampled[0:1].astype(np.float32),
        sdr_boost_nits=160.0,
        hdr_max_nits=1000.0,
    )[0]
    assert int(adaptive_expected[0]) > int(flat_expected[0])
    assert int(final[0, 0]) <= int(sampled[0, 0]) + 8


def test_process_frame_reference_style_neutral_grey() -> None:
    width, height, zone_count = 240, 140, 24
    zones_px = zones_from_config(
        make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="balanced"),
        width,
        height,
    )
    frame = np.full((height, width, 3), 128, dtype=np.uint8)
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        brightness=1.0,
        smoothing=1.0,
        color_style="reference",
        accuracy_mode=True,
        compositor_hdr_mode=True,
        sdr_boost_nits=200.0,
    )
    arr = np.asarray(colors, dtype=np.uint8)
    assert abs(float(arr[:, 0].mean()) - float(arr[:, 1].mean())) < 10.0
    assert abs(float(arr[:, 1].mean()) - float(arr[:, 2].mean())) < 10.0


def test_ring_buffer_pop_latest_returns_newest_item() -> None:
    buf: SPSCRingBuffer[int] = SPSCRingBuffer(capacity=2)
    assert buf.try_push(1)
    assert buf.try_push(2)
    assert buf.pop_latest(timeout=0.01) == 2
    assert buf.last_pop_coalesced == 1


def test_ring_buffer_pop_latest_coalesces_older_items() -> None:
    buf: SPSCRingBuffer[int] = SPSCRingBuffer(capacity=4)
    for value in (1, 2, 3):
        assert buf.try_push(value)
    assert buf.pop_latest(timeout=0.01) == 3
    assert buf.last_pop_coalesced == 2


def test_is_accuracy_mode_from_reference_style() -> None:
    assert is_accuracy_mode(False, "reference") is True
    assert is_accuracy_mode(False, "vivid") is False
