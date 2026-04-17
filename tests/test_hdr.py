from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.hdr import _pq_eotf_to_linear, convert_frame_to_srgb8


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
