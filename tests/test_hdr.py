from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.hdr import (
    _apply_tonemap_hable,
    _apply_tonemap_hable_luminance_preserving,
    _pq_eotf_to_linear,
    analyze_hdr_path,
    convert_frame_to_srgb8,
)


def test_hdr_conversion_contract_zero_is_zero() -> None:
    img = np.zeros((2, 3, 3), dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img, metadata={"transfer": "srgb", "primaries": "bt709", "max_nits": 1000.0}
    )
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    assert np.array_equal(out, np.zeros_like(out))


def test_hdr_conversion_contract_range_and_nonzero() -> None:
    # uint8=255 is encoded max; output should be in range and typically non-zero.
    img = np.full((1, 1, 3), 255, dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img, metadata={"transfer": "srgb", "primaries": "bt709", "max_nits": 1000.0}
    )
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    assert int(out[0, 0, 0]) >= 0
    assert int(out[0, 0, 0]) <= 255
    # Tone mapping will reduce peak slightly, but should still be > 0 for full-scale input.
    assert int(out[0, 0, 0]) > 0


def test_hdr_conversion_supports_pq_transfer() -> None:
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img, metadata={"transfer": "pq", "primaries": "bt2020", "max_nits": 1000.0}
    )
    assert np.array_equal(out, np.zeros_like(out))


def test_hdr_conversion_fast_path_returns_input_for_srgb_uint8() -> None:
    img = np.full((2, 3, 3), 77, dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img, metadata={"transfer": "srgb", "primaries": "bt709", "max_nits": 1000.0}
    )
    assert out is img


def test_pq_eotf_reference_100_nits() -> None:
    # ST2084 normalized code for 100 nits is approximately 0.508078.
    code = np.array([0.5080784], dtype=np.float32)
    linear = _pq_eotf_to_linear(code)
    assert linear.shape == code.shape
    assert np.isclose(float(linear[0]), 100.0 / 10000.0, rtol=0.05)


def test_hdr_conversion_fast_path_converts_srgb_float_to_uint8() -> None:
    img = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
    out = convert_frame_to_srgb8(
        img, metadata={"transfer": "srgb", "primaries": "bt709", "max_nits": 1000.0}
    )
    assert out.dtype == np.uint8
    assert out.shape == img.shape
    assert np.array_equal(out[0, 0], np.array([0, 128, 255], dtype=np.uint8))


def test_sdr_grey_in_hdr_path_does_not_collapse_to_black_or_tint() -> None:
    img = np.full((2, 2, 3), 128, dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img,
        metadata={"transfer": "pq", "primaries": "bt2020", "max_nits": 1000.0, "source": "unknown"},
    )
    assert abs(int(out[..., 0].mean()) - 128) <= 2
    assert abs(float(out[..., 0].mean()) - float(out[..., 1].mean())) < 4.0
    assert abs(float(out[..., 1].mean()) - float(out[..., 2].mean())) < 4.0


def test_hdr_analyzer_reports_no_tonemap_for_sdr_like_input() -> None:
    img = np.full((2, 2, 3), 96, dtype=np.uint8)
    diag = analyze_hdr_path(
        img,
        metadata={"transfer": "pq", "primaries": "bt2020", "max_nits": 1000.0, "source": "unknown"},
    )
    assert diag["tone_mapping_applied"] is False
    assert diag["input_transfer"] == "srgb"
    assert "SDR-like" in str(diag["assumption"])


def test_backend_pq_100_nit_grey_uses_hdr_tone_mapping() -> None:
    # ST2084 code for 100 nits should remain a visible diffuse grey, not dim black.
    img = np.full((2, 2, 3), 0.5080784, dtype=np.float32)
    diag = analyze_hdr_path(
        img,
        metadata={
            "transfer": "pq",
            "primaries": "bt2020",
            "max_nits": 1000.0,
            "source": "backend metadata",
        },
    )
    out = convert_frame_to_srgb8(
        img,
        metadata={
            "transfer": "pq",
            "primaries": "bt2020",
            "max_nits": 1000.0,
            "source": "backend metadata",
        },
    )
    assert diag["tone_mapping_applied"] is True
    assert int(out[..., 0].mean()) >= 120
    assert abs(float(out[..., 0].mean()) - float(out[..., 1].mean())) < 4.0


def test_pq_bt2020_representative_inputs_no_major_hue_shift() -> None:
    img = np.array([[[180, 30, 20], [20, 150, 30], [20, 40, 160]]], dtype=np.uint8)
    out = convert_frame_to_srgb8(
        img,
        metadata={
            "transfer": "pq",
            "primaries": "bt2020",
            "max_nits": 1000.0,
            "source": "backend metadata",
        },
    )
    assert out.dtype == np.uint8
    assert int(out[0, 0, 0]) >= int(out[0, 0, 1])
    assert int(out[0, 1, 1]) >= int(out[0, 1, 0])
    assert int(out[0, 2, 2]) >= int(out[0, 2, 1])


def test_hable_luminance_tonemap_preserves_neutral_grey() -> None:
    linear = np.full((2, 2, 3), 0.01, dtype=np.float32)
    mapped = _apply_tonemap_hable_luminance_preserving(linear, max_nits=1000.0)
    assert float(np.max(np.abs(mapped[..., 0] - mapped[..., 1]))) < 1e-6
    assert float(np.max(np.abs(mapped[..., 1] - mapped[..., 2]))) < 1e-6
    assert float(np.mean(mapped)) > float(np.mean(linear))


def test_hable_luminance_tonemap_preserves_rgb_ratios_better_than_per_channel() -> None:
    linear = np.asarray([[[0.02, 0.005, 0.0025]]], dtype=np.float32)
    per_channel = _apply_tonemap_hable(linear, max_nits=1000.0)
    luminance = _apply_tonemap_hable_luminance_preserving(linear, max_nits=1000.0)

    original_ratio = float(linear[0, 0, 1] / linear[0, 0, 0])
    per_channel_ratio = float(per_channel[0, 0, 1] / per_channel[0, 0, 0])
    luminance_ratio = float(luminance[0, 0, 1] / luminance[0, 0, 0])

    assert abs(luminance_ratio - original_ratio) < 0.01
    assert abs(luminance_ratio - original_ratio) < abs(per_channel_ratio - original_ratio)


def test_hable_tonemap_responds_to_max_nits_setting() -> None:
    linear = np.full((1, 1, 3), 0.05, dtype=np.float32)
    low_nits = _apply_tonemap_hable_luminance_preserving(linear, max_nits=400.0)
    high_nits = _apply_tonemap_hable_luminance_preserving(linear, max_nits=1000.0)
    assert float(np.mean(high_nits)) > float(np.mean(low_nits))


def test_missing_metadata_defaults_srgb() -> None:
    img = np.full((2, 2, 3), 128, dtype=np.uint8)
    out = convert_frame_to_srgb8(img, metadata={})
    assert out.dtype == np.uint8
    assert int(out[0, 0, 0]) > 0
