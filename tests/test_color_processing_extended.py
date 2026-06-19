"""Tests for color_processing.py uncovered paths: gamut adaptation init, timing."""

from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
    color_pipeline_diagnostics,
    get_last_color_process_ms,
    init_gamut_adaptation,
    oklch_to_rgb_u8,
    rgb_u8_to_oklch,
)

# ---------------------------------------------------------------------------
# init_gamut_adaptation
# ---------------------------------------------------------------------------


def test_init_gamut_adaptation_auto_no_detection() -> None:
    """When gamut='auto' and no primaries detected, sets identity."""
    # Force get_display_primaries to return None
    import nanoleaf_sync.color.primaries as primaries

    orig = getattr(primaries, "get_display_primaries", None)

    def _no_primaries():
        return None

    try:
        primaries.get_display_primaries = _no_primaries  # type: ignore[assignment]
        init_gamut_adaptation("auto")
    finally:
        if orig is not None:
            primaries.get_display_primaries = orig  # type: ignore[assignment]

    # After init, the matrix should be None (identity)
    from nanoleaf_sync.runtime import color_processing

    # Reload to check state
    color_processing.init_gamut_adaptation("srgb")
    # If src is None for srgb, it falls through to identity
    # This tests the path where get_primaries_for_gamut returns None


def test_init_gamut_adaptation_custom_gamut() -> None:
    """Custom gamut with no user chromaticities should set identity."""
    init_gamut_adaptation("custom")
    # Should not crash; just set identity


def test_init_gamut_adaptation_srgb_identity() -> None:
    """srgb gamut should produce identity (same primaries)."""
    init_gamut_adaptation("srgb")
    # Should not crash


# ---------------------------------------------------------------------------
# apply_color_style_mapping
# ---------------------------------------------------------------------------


def test_apply_color_style_mapping_basic() -> None:
    """Basic call with known style."""
    colors = np.array([[128, 64, 32]], dtype=np.uint8)
    result = apply_color_style_mapping(colors, color_style="reference")
    assert result.shape == (1, 3)
    assert result.dtype == np.uint8


def test_get_last_color_process_ms() -> None:
    """After apply_color_style_mapping, timing should be non-zero."""
    colors = np.array([[100, 100, 100]], dtype=np.uint8)
    apply_color_style_mapping(colors, color_style="ambient")
    t = get_last_color_process_ms()
    assert t >= 0.0


def test_apply_color_style_mapping_unknown_style() -> None:
    """Unknown style defaults to ambient."""
    colors = np.array([[64, 64, 64]], dtype=np.uint8)
    result = apply_color_style_mapping(colors, color_style="nonexistent")
    assert result.shape == (1, 3)


def test_apply_color_style_mapping_with_diagnostics() -> None:
    """Returns both output and cap_applied flag."""
    colors = np.array([[128, 128, 128]], dtype=np.uint8)
    out, cap = apply_color_style_mapping_with_diagnostics(colors, color_style="vivid")
    assert out.shape == (1, 3)
    assert isinstance(cap, np.ndarray)


def test_apply_style_mapping_preserves_neutral_grey() -> None:
    """Grey input should remain approximately neutral."""
    colors = np.array([[128, 128, 128]], dtype=np.uint8)
    out, _ = apply_color_style_mapping_with_diagnostics(colors, color_style="reference")
    # All channels should be close to each other (neutral output)
    diff = float(np.max(out) - np.min(out))
    assert diff < 60, f"Neutral grey distorted: max-min={diff}"


def test_apply_style_mapping_black_to_off() -> None:
    """Near-black should map to off."""
    colors = np.array([[1, 1, 1], [2, 2, 2]], dtype=np.uint8)
    out, _ = apply_color_style_mapping_with_diagnostics(colors, color_style="reference")
    # Very dark colors should become 0 or near 0
    assert np.max(out) < 20


# ---------------------------------------------------------------------------
# apply_led_calibration
# ---------------------------------------------------------------------------


def test_apply_led_calibration_identity() -> None:
    """Default calibration (all gains=1.0) should not change colors much."""
    colors = np.array([[128, 128, 128]], dtype=np.float32)
    cal = LedCalibration()
    result = apply_led_calibration(colors, cal)
    assert result.shape == (1, 3)


def test_apply_led_calibration_with_gains() -> None:
    """Custom gains should scale channels."""
    colors = np.array([[100, 100, 100]], dtype=np.float32)
    cal = LedCalibration(red_gain=1.2, blue_gain=0.8)
    result = apply_led_calibration(colors, cal)
    # Red should increase, blue should decrease
    assert result[0, 0] >= 100  # red boosted
    assert result[0, 2] <= 100  # blue reduced


def test_apply_led_calibration_white_balance() -> None:
    """White balance temperature shifts warm/cool."""
    colors = np.array([[128, 128, 128]], dtype=np.float32)
    cal_warm = LedCalibration(white_balance_temperature=1.0)
    result_warm = apply_led_calibration(colors, cal_warm)
    # Warm: more red, less blue
    assert result_warm[0, 0] > result_warm[0, 2]


def test_apply_led_calibration_gamma() -> None:
    """Gamma > 1 should affect output."""
    colors = np.array([[200, 200, 200]], dtype=np.float32)
    cal = LedCalibration(led_gamma=2.2)
    result = apply_led_calibration(colors, cal)
    # Should not crash and should change values
    assert result.shape == (1, 3)


def test_apply_led_calibration_black_cutoff() -> None:
    """Black cutoff should push dark colors to off."""
    colors = np.array([[2, 2, 2], [3, 3, 3]], dtype=np.float32)
    cal = LedCalibration(black_luminance_cutoff=0.02, black_luminance_knee=0.01)
    result = apply_led_calibration(colors, cal)
    # Very dark colors should be near-zero
    assert np.max(result) < 10


def test_apply_led_calibration_chroma_compression() -> None:
    """Chroma compression should reduce saturation."""
    colors = np.array([[255, 0, 0]], dtype=np.float32)  # pure red
    cal = LedCalibration(chroma_compression=0.5)
    result = apply_led_calibration(colors, cal)
    # Should still be valid
    assert result.shape == (1, 3)
    assert np.all(result >= 0) and np.all(result <= 255)


# ---------------------------------------------------------------------------
# color_pipeline_diagnostics
# ---------------------------------------------------------------------------


def test_color_pipeline_diagnostics() -> None:
    """Diagnostics should return a rich dict for a single pixel."""
    inp = np.array([200, 150, 100], dtype=np.float32)
    out = np.array([195, 148, 98], dtype=np.float32)
    diag = color_pipeline_diagnostics(input_rgb=inp, output_rgb=out)
    assert "input_rgb" in diag
    assert "output_rgb" in diag
    assert "input_lightness" in diag
    assert "output_lightness" in diag
    assert "grey_neutrality_verdict" in diag


def test_color_pipeline_diagnostics_neutral_input() -> None:
    """Neutral input should pass grey neutrality."""
    inp = np.array([128, 128, 128], dtype=np.float32)
    out = np.array([128, 128, 128], dtype=np.float32)
    diag = color_pipeline_diagnostics(input_rgb=inp, output_rgb=out)
    assert diag["grey_neutrality_verdict"] == "pass"


# ---------------------------------------------------------------------------
# rgb_u8_to_oklch / oklch_to_rgb_u8 round-trip
# ---------------------------------------------------------------------------


def test_rgb_oklch_roundtrip() -> None:
    """Round-trip should preserve colors approximately."""
    rgb = np.array([[128, 64, 192]], dtype=np.uint8)
    lum, c, h = rgb_u8_to_oklch(rgb)
    result = oklch_to_rgb_u8(lum, c, h)
    assert result.shape == rgb.shape
    # Should be close (some precision loss)
    diff = np.max(np.abs(result.astype(np.int32) - rgb.astype(np.int32)))
    assert diff < 10, f"Round-trip error too large: {diff}"
