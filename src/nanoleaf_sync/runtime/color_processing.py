from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gamut adaptation (display → sRGB)
# ---------------------------------------------------------------------------

_GAMUT_ADAPTATION_MATRIX: np.ndarray | None = None
_GAMUT_ADAPTATION_MATRIX_T: np.ndarray | None = None
_GAMUT_LOCK = threading.Lock()
_SKIP_DISPLAY_GAMUT: bool = False


def set_skip_display_gamut_adaptation(skip: bool) -> None:
    global _SKIP_DISPLAY_GAMUT
    _SKIP_DISPLAY_GAMUT = bool(skip)


def init_gamut_adaptation(
    display_gamut: str,
    *,
    custom_chromaticities: tuple[float, float, float, float, float, float] | None = None,
) -> None:
    """Initialise the gamut adaptation matrix from display primaries → sRGB.

    Called once at pipeline start with the config ``display_gamut`` value.
    When ``display_gamut`` is ``"auto"``, auto-detection is attempted via
    colord / EDID.  When the gamut is already sRGB (or detection fails),
    the adaptation is an identity (``None`` internally).
    """
    global _GAMUT_ADAPTATION_MATRIX, _GAMUT_ADAPTATION_MATRIX_T

    from nanoleaf_sync.color.primaries import (
        CHROMATICITIES_SRGB,
        Chromaticities,
        build_adaptation_matrix,
        get_display_primaries,
    )

    gamut = str(display_gamut or "auto").strip().lower()

    src: Chromaticities | None
    if gamut == "custom" and custom_chromaticities is not None:
        rx, ry, gx, gy, bx, by = custom_chromaticities
        src = Chromaticities(
            rx=float(rx),
            ry=float(ry),
            gx=float(gx),
            gy=float(gy),
            bx=float(bx),
            by=float(by),
            wx=0.3127,
            wy=0.3290,
        )
    elif gamut == "auto":
        src = get_display_primaries()
    else:
        from nanoleaf_sync.color.primaries import get_primaries_for_gamut

        src = get_primaries_for_gamut(gamut)

    if src is None:
        if gamut == "custom":
            _log.warning(
                "Gamut adaptation: 'custom' display gamut selected but chromaticities "
                "are missing; using identity (sRGB)"
            )
        else:
            _log.debug("Gamut adaptation: no display primaries detected; using identity (sRGB)")
        with _GAMUT_LOCK:
            _GAMUT_ADAPTATION_MATRIX = None
            _GAMUT_ADAPTATION_MATRIX_T = None
        return

    new_matrix = build_adaptation_matrix(src, CHROMATICITIES_SRGB)
    new_matrix_t = np.ascontiguousarray(new_matrix.T)
    with _GAMUT_LOCK:
        _GAMUT_ADAPTATION_MATRIX = new_matrix
        _GAMUT_ADAPTATION_MATRIX_T = new_matrix_t
    _log.debug(
        "Gamut adaptation: display primaries r=(%.3f,%.3f) g=(%.3f,%.3f) b=(%.3f,%.3f)",
        src.rx,
        src.ry,
        src.gx,
        src.gy,
        src.bx,
        src.by,
    )


_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
)
_M1_INV = np.array(
    [
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ],
    dtype=np.float32,
)
_M2_INV = np.array(
    [
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480],
    ],
    dtype=np.float32,
)
_M1_T = np.ascontiguousarray(_M1.T)
_M2_T = np.ascontiguousarray(_M2.T)
_M1_INV_T = np.ascontiguousarray(_M1_INV.T)
_M2_INV_T = np.ascontiguousarray(_M2_INV.T)


@dataclass(frozen=True)
class StyleProfile:
    chroma_boost: float
    chroma_cap_ratio: float
    chroma_compression: float
    black_luminance_cutoff: float
    black_luminance_knee: float
    neutral_chroma_threshold: float
    neutral_chroma_knee: float
    neutral_luminance_floor: float
    neutral_luminance_gain: float


STYLE_PROFILES = {
    "reference": StyleProfile(1.0, 1.05, 0.0, 0.0032, 0.0024, 0.028, 0.010, 0.0, 1.00),
    "natural": StyleProfile(1.0, 1.05, 0.0, 0.0032, 0.0024, 0.028, 0.010, 0.0, 1.00),
    "ambient": StyleProfile(1.0, 1.08, 0.0, 0.0028, 0.0028, 0.032, 0.012, 0.0, 1.08),
    "vivid": StyleProfile(1.10, 1.28, 0.07, 0.0018, 0.0018, 0.024, 0.010, 0.0, 1.04),
    "punchy": StyleProfile(1.20, 1.42, 0.05, 0.0018, 0.0018, 0.022, 0.010, 0.0, 1.06),
}


@dataclass(frozen=True)
class LedCalibration:
    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    led_gamma: float = 1.0
    white_balance_temperature: float = 0.0
    chroma_compression: float = 0.0
    neutral_luminance_gain: float = 1.0
    black_luminance_cutoff: float = 0.0032
    black_luminance_knee: float = 0.0024
    color_matrix: tuple[float, ...] = ()


def apply_display_gamut_adaptation(colors: np.ndarray) -> np.ndarray:
    if _SKIP_DISPLAY_GAMUT:
        return colors
    rgb = np.clip(np.rint(colors), 0.0, 255.0).astype(np.uint8, copy=False)
    linear = srgb_u8_to_linear01(rgb)
    with _GAMUT_LOCK:
        matrix_t = _GAMUT_ADAPTATION_MATRIX_T
    if matrix_t is None:
        return colors.astype(np.float32, copy=False)
    linear = np.clip(linear @ matrix_t, 0.0, 1.0)
    return linear01_to_srgb_u8(linear).astype(np.float32, copy=False)


def _planckian_white_balance_gains(temperature: float) -> np.ndarray:
    wb = float(np.clip(temperature, -1.0, 1.0))
    if abs(wb) < 1e-6:
        return np.asarray([1.0, 1.0, 1.0], dtype=np.float32)
    warm = wb > 0.0
    scale = abs(wb)
    if warm:
        return np.asarray([1.0 + (0.10 * scale), 1.0, 1.0 - (0.06 * scale)], dtype=np.float32)
    return np.asarray([1.0 - (0.06 * scale), 1.0, 1.0 + (0.10 * scale)], dtype=np.float32)


def _linear_to_oklab(linear_rgb: np.ndarray) -> np.ndarray:
    lms = linear_rgb @ _M1_T
    lms_cbrt = np.cbrt(np.clip(lms, 0.0, None))
    return lms_cbrt @ _M2_T


def _oklab_to_linear(oklab: np.ndarray) -> np.ndarray:
    lms_cbrt = oklab @ _M2_INV_T
    lms = lms_cbrt * lms_cbrt * lms_cbrt
    return lms @ _M1_INV_T


def _smoothstep(edge0: np.ndarray, edge1: np.ndarray, x: np.ndarray) -> np.ndarray:
    width = np.maximum(edge1 - edge0, 1e-6)
    t = np.clip((x - edge0) / width, 0.0, 1.0)
    return t * t * (3.0 - (2.0 * t))


def rgb_u8_to_oklch(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    linear = srgb_u8_to_linear01(np.asarray(rgb, dtype=np.uint8))
    oklab = _linear_to_oklab(linear)
    a = oklab[..., 1]
    b = oklab[..., 2]
    c = np.sqrt((a * a) + (b * b))
    h = np.arctan2(b, a)
    return oklab[..., 0], c, h


def oklch_to_rgb_u8(lum: np.ndarray, c: np.ndarray, h: np.ndarray) -> np.ndarray:
    a = c * np.cos(h)
    b = c * np.sin(h)
    oklab = np.stack((lum, a, b), axis=-1)
    linear = _oklab_to_linear(oklab)
    return linear01_to_srgb_u8(linear)


def apply_color_style_mapping_with_diagnostics(
    colors: np.ndarray, *, color_style: str
) -> tuple[np.ndarray, np.ndarray]:
    style = STYLE_PROFILES.get(str(color_style).strip().lower(), STYLE_PROFILES["ambient"])
    rgb = np.clip(np.rint(colors), 0.0, 255.0).astype(np.uint8, copy=False)
    linear = srgb_u8_to_linear01(rgb)

    y = np.clip(
        (0.2126 * linear[..., 0]) + (0.7152 * linear[..., 1]) + (0.0722 * linear[..., 2]),
        0.0,
        1.0,
    )
    lum, c, h = rgb_u8_to_oklch(rgb)

    c_boosted = c * style.chroma_boost
    c_cap = c * style.chroma_cap_ratio
    cap_applied = c_boosted > c_cap + 1e-7
    c_capped = np.minimum(c_boosted, c_cap)
    c_mapped = c_capped / (1.0 + (style.chroma_compression * c_capped))

    # Luminance model:
    # - near-black falls to off via a smooth knee
    # - low chroma preserves neutral luminance and trends to white
    # - moderate chroma blends neutral luminance and sampled hue
    # - high chroma follows hue with per-style chroma caps/compression
    black_gate = _smoothstep(
        np.full_like(y, style.black_luminance_cutoff - style.black_luminance_knee),
        np.full_like(y, style.black_luminance_cutoff + style.black_luminance_knee),
        y,
    )
    neutral_weight = 1.0 - _smoothstep(
        np.full_like(c, max(0.0, style.neutral_chroma_threshold - style.neutral_chroma_knee)),
        np.full_like(c, style.neutral_chroma_threshold + style.neutral_chroma_knee),
        c,
    )
    neutral_y = np.clip(
        (np.maximum(y, style.neutral_luminance_floor) * style.neutral_luminance_gain), 0.0, 1.0
    )
    neutral_l = np.cbrt(neutral_y)
    lum_mapped = np.clip((neutral_l * neutral_weight) + (lum * (1.0 - neutral_weight)), 0.0, 1.0)
    c_mapped = c_mapped * (1.0 - (0.92 * neutral_weight))

    lum_mapped *= black_gate
    c_mapped *= black_gate

    out = oklch_to_rgb_u8(
        lum_mapped.astype(np.float32), c_mapped.astype(np.float32), h.astype(np.float32)
    )
    return out, cap_applied


_last_color_process_ms: float = 0.0


def get_last_color_process_ms() -> float:
    return _last_color_process_ms


def apply_color_style_mapping(colors: np.ndarray, *, color_style: str) -> np.ndarray:
    t0 = time.perf_counter()
    out, _ = apply_color_style_mapping_with_diagnostics(colors, color_style=color_style)
    t1 = time.perf_counter()
    global _last_color_process_ms
    _last_color_process_ms = (t1 - t0) * 1000
    return out


def apply_led_calibration(colors: np.ndarray, calibration: LedCalibration) -> np.ndarray:
    rgb = np.clip(np.asarray(colors, dtype=np.float32), 0.0, 255.0)
    gains = np.asarray(
        [calibration.red_gain, calibration.green_gain, calibration.blue_gain], dtype=np.float32
    )
    rgb *= np.clip(gains, 0.5, 1.5)

    matrix_values = tuple(float(v) for v in (calibration.color_matrix or ()))
    if len(matrix_values) == 9:
        linear = srgb_u8_to_linear01(np.clip(np.rint(rgb), 0.0, 255.0).astype(np.uint8, copy=False))
        matrix = np.asarray(matrix_values, dtype=np.float32).reshape(3, 3)
        linear = np.clip(linear @ matrix.T, 0.0, 1.0)
        rgb = linear01_to_srgb_u8(linear).astype(np.float32)

    wb_gain = _planckian_white_balance_gains(float(calibration.white_balance_temperature))
    rgb *= wb_gain

    rgb8 = np.clip(np.rint(rgb), 0.0, 255.0).astype(np.uint8, copy=False)
    lum, c, h = rgb_u8_to_oklch(rgb8)
    c = c / (1.0 + (np.clip(float(calibration.chroma_compression), 0.0, 0.6) * c))

    neutral_w = np.clip((0.03 - c) / 0.03, 0.0, 1.0)
    neutral_gain = np.clip(float(calibration.neutral_luminance_gain), 0.7, 1.5)
    lum = np.clip(lum * (1.0 + (neutral_gain - 1.0) * neutral_w), 0.0, 1.0)
    out = oklch_to_rgb_u8(
        lum.astype(np.float32), c.astype(np.float32), h.astype(np.float32)
    ).astype(np.float32)

    cutoff = np.clip(float(calibration.black_luminance_cutoff), 0.0, 0.03)
    knee = np.clip(float(calibration.black_luminance_knee), 0.0005, 0.03)
    if cutoff > 0.0:
        out_linear = srgb_u8_to_linear01(
            np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8, copy=False)
        )
        y = np.clip(
            (0.2126 * out_linear[..., 0])
            + (0.7152 * out_linear[..., 1])
            + (0.0722 * out_linear[..., 2]),
            0.0,
            1.0,
        )
        gate = _smoothstep(
            np.full_like(y, max(0.0, cutoff - knee)),
            np.full_like(y, cutoff + knee),
            y,
        )[..., None]
        out *= gate

    gamma = np.clip(float(calibration.led_gamma), 1.0, 4.0)
    if abs(gamma - 1.0) > 1e-6:
        out = np.power(np.clip(out / 255.0, 0.0, 1.0), 1.0 / gamma) * 255.0
    return np.clip(out, 0.0, 255.0)


def color_pipeline_diagnostics(
    *,
    input_rgb: Any,
    output_rgb: Any,
    chroma_cap_applied: bool = False,
    color_style: str = "reference",
) -> dict[str, float | bool | str | tuple[int, ...]]:
    in_rgb = np.clip(np.rint(np.asarray(input_rgb, dtype=np.float32)), 0.0, 255.0).astype(np.uint8)
    out_rgb = np.clip(np.rint(np.asarray(output_rgb, dtype=np.float32)), 0.0, 255.0).astype(
        np.uint8
    )
    style = STYLE_PROFILES.get(str(color_style).strip().lower(), STYLE_PROFILES["ambient"])
    l_in, c_in, h_in = rgb_u8_to_oklch(in_rgb[None, :])
    l_out, c_out, h_out = rgb_u8_to_oklch(out_rgb[None, :])
    c_in_v = float(c_in[0])
    c_out_v = float(c_out[0])
    l_in_v = float(l_in[0])
    l_out_v = float(l_out[0])
    in_linear = srgb_u8_to_linear01(in_rgb[None, :])[0]
    out_linear = srgb_u8_to_linear01(out_rgb[None, :])[0]
    y_in_v = float(
        np.clip(
            (0.2126 * in_linear[0]) + (0.7152 * in_linear[1]) + (0.0722 * in_linear[2]), 0.0, 1.0
        )
    )
    y_out_v = float(
        np.clip(
            (0.2126 * out_linear[0]) + (0.7152 * out_linear[1]) + (0.0722 * out_linear[2]), 0.0, 1.0
        )
    )
    hue_diff = float(np.degrees(np.arctan2(np.sin(h_out[0] - h_in[0]), np.cos(h_out[0] - h_in[0]))))
    neutral_in = c_in_v < 0.015
    neutral_out = c_out_v < 0.015
    black_cutoff_applied = bool(
        y_in_v <= (style.black_luminance_cutoff + style.black_luminance_knee) and y_out_v < 0.002
    )
    neutral_floor_applied = bool(
        c_in_v <= (style.neutral_chroma_threshold + style.neutral_chroma_knee)
        and y_out_v >= min(1.0, y_in_v * style.neutral_luminance_gain)
    )
    grey_neutrality_ok = bool((not neutral_in) or neutral_out)
    black_cutoff_ok = bool(
        (y_in_v > style.black_luminance_cutoff)
        or y_out_v <= max(0.002, style.black_luminance_cutoff + style.black_luminance_knee)
    )
    return {
        "input_rgb": tuple(int(v) for v in in_rgb.tolist()),
        "output_rgb": tuple(int(v) for v in out_rgb.tolist()),
        "input_lightness": l_in_v,
        "output_lightness": l_out_v,
        "input_chroma": c_in_v,
        "sampled_luminance": y_in_v,
        "output_luminance": y_out_v,
        "sampled_chroma": c_in_v,
        "output_chroma": c_out_v,
        "input_hue_degrees": float(np.degrees(h_in[0])),
        "output_hue_degrees": float(np.degrees(h_out[0])),
        "chroma_ratio": float(c_out_v / c_in_v) if c_in_v > 1e-6 else 1.0,
        "hue_difference_degrees": 0.0 if neutral_in else hue_diff,
        "neutral_grey_preserved": grey_neutrality_ok,
        "grey_neutrality_verdict": "pass" if grey_neutrality_ok else "fail",
        "black_cutoff_verdict": "pass" if black_cutoff_ok else "fail",
        "neutral_luminance_output_value": l_out_v,
        "neutral_floor_applied": neutral_floor_applied,
        "black_cutoff_applied": black_cutoff_applied,
        "chroma_cap_applied": bool(chroma_cap_applied),
        "led_calibration_applied": tuple(int(v) for v in in_rgb.tolist())
        != tuple(int(v) for v in out_rgb.tolist()),
    }
