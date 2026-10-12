"""Development bridge contracts; fake failures run without a native build."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from nanoleaf_sync.config.model import PrivacyZone
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams
from nanoleaf_sync.runtime.color_processing import LedCalibration
from nanoleaf_sync.runtime.engine_frame import process_frame
from nanoleaf_sync.runtime.rust_sampling import RustBoxSampler, load_rust_box_sampler
from nanoleaf_sync.runtime.zones import _zone_colors_via_box_filter, zone_colors_array


@pytest.fixture
def native() -> RustBoxSampler:
    path = os.environ.get("NANOLEAF_RUST_BRIDGE")
    if not path:
        pytest.skip("Explicit development bridge path not supplied")
    return load_rust_box_sampler(Path(path))


def test_native_failure_disables_once_and_python_remains_usable() -> None:
    calls = []

    def fail(*args: object) -> object:
        calls.append(args)
        raise RuntimeError("injected native failure")

    sampler = RustBoxSampler(SimpleNamespace(sample=fail), compiler="fake")
    frame = np.full((7, 11, 3), 128, dtype=np.uint8)
    zones = [(0, 0, 11, 7)]
    for _ in range(3):
        colors, variance = _zone_colors_via_box_filter(
            frame, zones, edge_locality="balanced", use_multi_moment=False, box_sampler=sampler
        )
        np.testing.assert_array_equal(colors, [[128, 128, 128]])
        np.testing.assert_array_equal(variance, [0])
    assert len(calls) == 1
    assert sampler.disabled_reason == "RuntimeError: injected native failure"


@pytest.mark.parametrize("result", [(b"", b""), (b"\x00" * 3, np.float32(np.nan).tobytes())])
def test_malformed_native_result_falls_back(result: tuple[bytes, bytes]) -> None:
    sampler = RustBoxSampler(SimpleNamespace(sample=lambda *args: result), compiler="fake")
    image = np.full((1, 1, 3), 255, dtype=np.uint8)
    colors, _ = _zone_colors_via_box_filter(
        image, [(0, 0, 1, 1)], edge_locality="balanced", use_multi_moment=False, box_sampler=sampler
    )
    np.testing.assert_array_equal(colors, [[255, 255, 255]])
    assert sampler.disabled_reason is not None


def test_loading_requires_an_explicit_existing_extension(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_rust_box_sampler(tmp_path / "absent.so")
    text = tmp_path / "not-an-extension.txt"
    text.write_text("not executable")
    with pytest.raises(ImportError):
        load_rust_box_sampler(text)
    python_source = tmp_path / "not-an-extension.py"
    python_source.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ImportError):
        load_rust_box_sampler(python_source)


@pytest.mark.parametrize("case", ["float", "multi_moment", "palette", "virtual"])
def test_unsupported_paths_do_not_call_bridge(case: str) -> None:
    calls = []

    def spy(*args: object) -> None:
        calls.append(args)

    frame = np.full((17, 23, 3), 128, dtype=np.uint8)
    kwargs = dict(use_zone_box_filter=True, sampling_mode="area_average", box_sampler=spy)
    if case == "float":
        frame = frame.astype(np.float32)
    if case == "multi_moment":
        kwargs["multi_moment_zone_colors"] = True
    if case == "palette":
        kwargs["sampling_mode"] = "palette_adaptive"
    if case == "virtual":
        kwargs["virtual_oversample"] = 8
    zone_colors_array(frame, [(0, 0, 23, 17)], **kwargs)
    assert not calls


@pytest.mark.parametrize("metadata", ["hdr", "pq", "bt2020"])
def test_hdr_or_wide_gamut_pipeline_stays_python(metadata: str) -> None:
    calls = []

    def spy(*args: object) -> None:
        calls.append(args)

    params = ColorPipelineParams(
        sampling_mode="area_average",
        use_zone_box_filter=True,
        box_sampler=spy,
        compositor_hdr_mode=metadata == "hdr",
        color_context=SimpleNamespace(
            transfer="pq" if metadata == "pq" else "srgb",
            primaries="bt2020" if metadata == "bt2020" else "bt709",
        ),
    )
    process_frame(
        frame=np.full((7, 11, 3), 128, dtype=np.uint8),
        prev_smoothed_colors=[(0, 0, 0)],
        zones_px=[(0, 0, 11, 7)],
        device_zone_indices=[0],
        params=params,
    )
    assert not calls


@pytest.mark.parametrize("view", ["contiguous", "padded", "reversed", "channels"])
@pytest.mark.parametrize("anchor", [True, False])
def test_native_views_privacy_clipping_and_variance(
    native: RustBoxSampler, view: str, anchor: bool
) -> None:
    frame = np.random.default_rng(42).integers(0, 256, (33, 37, 3), dtype=np.uint8)
    if view == "padded":
        padded = np.zeros((33, 45, 3), dtype=np.uint8)
        padded[:, :37] = frame
        frame = padded[:, :37]
    elif view == "reversed":
        frame = frame[::-1, ::-1]
    elif view == "channels":
        frame = frame[:, :, ::-1]
    zones = [
        (0, 0, 4, 33),
        (30, 30, 20, 20),
        (-7, -9, 3, 4),
        (99, 99, 1, 1),
        (0, 0, 0, 0),
        (5, 7, 13, 19),
        (-100, -100, 150, 150),
    ]
    kwargs = dict(
        edge_locality="tight",
        use_multi_moment=False,
        edge_anchor=anchor,
        privacy_zones=[PrivacyZone(x=0.2, y=0.3, w=0.3, h=0.4)],
    )
    python_rgb, python_var = _zone_colors_via_box_filter(frame, zones, **kwargs)
    rust_rgb, rust_var = _zone_colors_via_box_filter(frame, zones, box_sampler=native, **kwargs)
    np.testing.assert_array_equal(rust_rgb, python_rgb)
    np.testing.assert_allclose(rust_var, python_var, rtol=0, atol=0.002)
    assert native.successful_calls == 1
    assert native.disabled_reason is None


def test_native_neutral_ramp(native: RustBoxSampler) -> None:
    frame = np.repeat(np.arange(256, dtype=np.uint8)[:, None, None], 3, axis=2)
    zones = [(0, i, 1, 1) for i in range(256)]
    colors, variance = native(frame, zones)
    np.testing.assert_array_equal(colors, frame[:, 0])
    np.testing.assert_array_equal(variance, np.zeros(256))


def test_native_rejects_hdr_and_truncated_bytes(native: RustBoxSampler) -> None:
    with pytest.raises(ValueError, match="SDR"):
        native._native.sample(b"\x00" * 3, 1, 1, [(0, 0, 1, 1)], "pq")
    with pytest.raises(ValueError, match="TruncatedFrame"):
        native._native.sample(b"", 1, 1, [(0, 0, 1, 1)], "srgb")


def test_full_calibrated_sequence_preserves_mapping_and_output(native: RustBoxSampler) -> None:
    zones = [(0, 0, 17, 19), (17, 0, 20, 19), (0, 19, 37, 14)]
    calibration = LedCalibration(
        red_gain=0.85,
        green_gain=1.05,
        blue_gain=0.9,
        led_gamma=1.1,
        color_matrix=(0.95, 0.03, 0.02, 0.01, 0.98, 0.01, 0.02, 0.03, 0.95),
    )
    params = ColorPipelineParams(
        sampling_mode="area_average",
        use_zone_box_filter=True,
        led_calibration=calibration,
        letterbox_detection=True,
        privacy_zones=[PrivacyZone(x=0.2, y=0.3, w=0.3, h=0.4)],
    )
    histories = [[(0, 0, 0)] * 3, [(0, 0, 0)] * 3]
    for index in range(20):
        frame = np.random.default_rng(index).integers(0, 256, (33, 37, 3), dtype=np.uint8)
        if index % 4 == 0:
            frame[:] = (0, 128, 255)[index % 3]
        for side in range(2):
            histories[side] = process_frame(
                frame=frame,
                prev_smoothed_colors=histories[side],
                zones_px=zones,
                device_zone_indices=[2, 0, 1],
                params=replace(params, box_sampler=native if side else None),
            )
        assert histories[0] == histories[1]
    assert native.successful_calls == 20


def test_temporal_accumulation_and_dither_replay(native: RustBoxSampler) -> None:
    from nanoleaf_sync.runtime.color_pipeline import process_zone_colors

    params = ColorPipelineParams(
        sampling_mode="area_average",
        use_zone_box_filter=True,
        zone_temporal_accumulation=True,
        blue_noise_dither=True,
    )
    frames = [
        np.random.default_rng(index).integers(0, 256, (19, 31, 3), dtype=np.uint8)
        for index in range(16)
    ]
    outputs = []
    try:
        for side in range(2):
            process_zone_colors._zone_accumulator = None
            history = [(0, 0, 0)] * 2
            replay = []
            for index, frame in enumerate(frames):
                history = process_frame(
                    frame=frame,
                    prev_smoothed_colors=history,
                    zones_px=[(0, 0, 15, 19), (15, 0, 16, 19)],
                    device_zone_indices=[1, 0],
                    params=replace(
                        params, box_sampler=native if side else None, palette_frame_index=index
                    ),
                )
                replay.append(history)
            outputs.append(replay)
        assert outputs[0] == outputs[1]
        assert native.successful_calls == len(frames)
    finally:
        process_zone_colors._zone_accumulator = None
