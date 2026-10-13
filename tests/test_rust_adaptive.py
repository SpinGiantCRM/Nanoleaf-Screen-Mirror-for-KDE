"""Strict adaptive prepass colour/decision parity, including preserved Python fallback."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from nanoleaf_sync.config.model import PrivacyZone
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams
from nanoleaf_sync.runtime.engine_frame import process_frame
from nanoleaf_sync.runtime.rust_sampling import RustBoxSampler, load_rust_box_sampler
from nanoleaf_sync.runtime.zones import (
    _dark_biased_patch_mean,
    detect_zone_patch_mixed_content,
    zone_colors_array_with_meta,
)


@pytest.fixture
def native() -> RustBoxSampler:
    path = os.environ.get("NANOLEAF_RUST_BRIDGE")
    if not path:
        pytest.skip("Explicit development native extension not supplied")
    return load_rust_box_sampler(Path(path))


@pytest.mark.parametrize("payload", [(b"", b""), (b"\x03", b"\x00" * 3), None])
def test_invalid_or_missing_kernel_falls_back_and_disables_once(payload: object) -> None:
    calls = []

    def fail(*args: object):
        calls.append(args)
        if payload is None:
            raise RuntimeError("injected failure")
        return payload

    sampler = RustBoxSampler(SimpleNamespace(adaptive_prepass=fail), compiler="fake")
    frame = np.full((7, 11, 3), (25, 170, 45), dtype=np.uint8)
    baseline = zone_colors_array_with_meta(frame, [(0, 0, 11, 7)], sampling_mode="palette_adaptive")
    for _ in range(3):
        colors, meta = zone_colors_array_with_meta(
            frame,
            [(0, 0, 11, 7)],
            sampling_mode="palette_adaptive",
            adaptive_prepass=sampler.adaptive_prepass,
        )
        np.testing.assert_array_equal(colors, baseline[0])
        assert meta == baseline[1]
    assert len(calls) == 1
    assert sampler.disabled_reason is not None


def test_reference_decision_keeps_python_colour_and_diagnostics() -> None:
    fake = RustBoxSampler(
        SimpleNamespace(adaptive_prepass=lambda *args: (b"\x02", b"\xff" * 3)), compiler="fake"
    )
    frame = np.zeros((19, 31, 3), dtype=np.uint8)
    frame[:, 15:] = 255
    expected = zone_colors_array_with_meta(
        frame, [(0, 0, 31, 19)], sampling_mode="palette_adaptive"
    )
    colors, meta = zone_colors_array_with_meta(
        frame,
        [(0, 0, 31, 19)],
        sampling_mode="palette_adaptive",
        adaptive_prepass=fake.adaptive_prepass,
    )
    np.testing.assert_array_equal(colors, expected[0])
    assert meta == expected[1]
    assert fake.adaptive_reference_zones == 1
    assert fake.disabled_reason is None


def test_inverted_geometry_uses_original_python_path() -> None:
    calls = []

    def spy(*args: object):
        calls.append(args)

    frame = np.full((33, 37, 3), 128, np.uint8)
    # Two negative dimensions can give a positive cached area; do not skip the
    # original integral pass when the overwrite proof does not hold.
    zones = [(20, 20, -3, -4), (0, 0, 7, 9)]
    for prepass in (None, spy):
        with pytest.raises(IndexError):
            zone_colors_array_with_meta(
                frame, zones, sampling_mode="palette_adaptive", adaptive_prepass=prepass
            )
    assert not calls


@pytest.mark.parametrize("case", ["hdr", "pq", "bt2020", "float", "box", "virtual"])
def test_unsupported_pipeline_keeps_python(case: str) -> None:
    calls = []

    def spy(*args: object):
        calls.append(args)

    params = ColorPipelineParams(
        color_style="ambient",
        sampling_mode="palette_adaptive",
        adaptive_prepass=spy,
        compositor_hdr_mode=case == "hdr",
    )
    if case in {"pq", "bt2020"}:
        params = replace(
            params,
            color_context=SimpleNamespace(
                transfer="pq" if case == "pq" else "srgb",
                primaries="bt2020" if case == "bt2020" else "bt709",
            ),
        )
    if case == "box":
        params = replace(params, sampling_mode="area_average", use_zone_box_filter=True)
    if case == "virtual":
        params = replace(params, virtual_oversample=8)
    frame = np.full((7, 11, 3), 128, dtype=np.float32 if case == "float" else np.uint8)
    process_frame(
        frame=frame,
        prev_smoothed_colors=[(0, 0, 0)],
        zones_px=[(0, 0, 11, 7)],
        device_zone_indices=[0],
        params=params,
    )
    assert not calls


def test_native_fuzzed_decisions_and_mixed_rgb(native: RustBoxSampler) -> None:
    reference = 0
    for index in range(400):
        rng = np.random.default_rng(index)
        height, width = (int(v) for v in rng.integers(1, 180, 2))
        frame = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
        if index % 4 == 0:
            frame = rng.integers(0, 32, frame.shape, dtype=np.uint8)
        if index % 4 == 1:
            frame[:] = rng.integers(0, 256, 3)
            frame[: height // 4] = rng.integers(0, 256, 3)
        if index % 4 == 2:
            frame[:] = 128
            frame[: height // 2, :, 0] = 130
        status, colors = native.adaptive_prepass(frame, [(0, 0, width, height)])
        if status[0] == 2:
            reference += 1
            continue
        assert bool(status[0]) == detect_zone_patch_mixed_content(frame), index
        if status[0] == 1:
            np.testing.assert_array_equal(
                colors[0], _dark_biased_patch_mean(frame), err_msg=str(index)
            )
    assert reference > 0
    assert native.disabled_reason is None


@pytest.mark.parametrize("mode", ["balanced", "dynamic", "hyper"])
@pytest.mark.parametrize("step", [1, 2, 3])
def test_native_zone_sequence_mapping_masks_and_temporal_parity(
    native: RustBoxSampler, mode: str, step: int
) -> None:
    states = [None, None]
    previous = [None, None]
    zones = [(0, 0, 9, 33), (9, 0, 28, 33), (-9, -7, 12, 13), (99, 99, 2, 3)]
    for index in range(12):
        frame = np.full((33, 37, 3), (25, 170, 45) if index < 6 else (210, 20, 25), dtype=np.uint8)
        if index % 3 == 1:
            frame[2:12, 1:8] = 255
        if index % 3 == 2:
            frame = np.random.default_rng(index).integers(0, 32, frame.shape, dtype=np.uint8)
        if index == 10:
            frame[:] = 128
        if index == 11:
            frame[:] = 0
        padded = np.zeros((33, 45, 3), np.uint8)
        padded[:, :37] = frame
        frame = padded[:, :37, ::-1]
        results = []
        for side in range(2):
            rgb, meta = zone_colors_array_with_meta(
                frame,
                zones,
                sampling_mode="palette_adaptive",
                mode=mode,
                sample_step=step,
                privacy_zones=[PrivacyZone(x=0.15, y=0.2, w=0.3, h=0.4)],
                palette_temporal_states=states[side],
                previous_zone_colors=previous[side],
                palette_frame_index=index,
                global_scene_cut=index == 6,
                adaptive_prepass=native.adaptive_prepass if side else None,
            )
            states[side] = meta.per_zone_palette_temporal_states
            previous[side] = rgb.tolist()
            results.append((rgb, meta))
        np.testing.assert_array_equal(results[0][0], results[1][0])
        assert results[0][1] == results[1][1]
    assert native.adaptive_calls > 0


def test_native_all_neutrals_and_guarded_scratch_budget(native: RustBoxSampler) -> None:
    frame = np.repeat(np.arange(256, dtype=np.uint8)[:, None, None], 3, axis=2)
    status, _ = native.adaptive_prepass(frame, [(0, i, 1, 1) for i in range(256)])
    np.testing.assert_array_equal(status, np.zeros(256, np.uint8))
    large = np.zeros((1024, 1025, 3), np.uint8)
    status, _ = native.adaptive_prepass(large, [(0, 0, 1025, 1024)])
    assert status[0] == 2
    with pytest.raises(ValueError, match="SDR"):
        native._native.adaptive_prepass(b"\x00" * 3, 1, 1, [(0, 0, 1, 1)], "pq")
    with pytest.raises(ValueError, match="TruncatedFrame"):
        native._native.adaptive_prepass(b"", 1, 1, [(0, 0, 1, 1)], "srgb")
