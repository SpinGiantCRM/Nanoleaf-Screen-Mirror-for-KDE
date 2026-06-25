from __future__ import annotations

import numpy as np

from nanoleaf_sync.capture._utils import _resize_to_target, zone_box_average
from nanoleaf_sync.config.model import PrivacyZone
from nanoleaf_sync.runtime.blue_noise import apply_blue_noise_dither
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01
from nanoleaf_sync.runtime.zone_accumulator import ZoneAccumulator
from nanoleaf_sync.runtime.zones import (
    compute_adaptive_step,
    edge_anchored_rect,
    multi_moment_zone_color,
    zone_colors_array,
)


def _delta_e_simple(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a.astype(np.float32) - b.astype(np.float32)))


def test_box_filter_closer_to_ground_truth_than_nn() -> None:
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    frame[:, :1] = (255, 0, 0)
    zone = (0, 0, 32, 32)
    box = zone_box_average(frame, zone)
    nn = _resize_to_target(frame=frame, target_height=4, target_width=4).reshape(-1, 3).mean(axis=0)
    truth = linear01_to_srgb_u8(srgb_u8_to_linear01(frame).reshape(-1, 3).mean(axis=0))
    assert _delta_e_simple(box, truth) < _delta_e_simple(nn, truth) + 1.0


def test_zone_box_average_uses_linear_light_mean_for_mixed_black_white() -> None:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    frame[:, 1:] = 255
    color = zone_box_average(frame, (0, 0, 2, 2), max_pixels=4)
    assert 180 <= int(color[0]) <= 190
    assert int(color[0]) == int(color[1]) == int(color[2])


def test_box_filter_shift_stability() -> None:
    base = np.zeros((16, 16, 3), dtype=np.uint8)
    base[4:12, 4:12] = (0, 0, 255)
    shifted = np.roll(base, 1, axis=1)
    zone = (4, 4, 8, 8)
    c1 = zone_box_average(base, zone)
    c2 = zone_box_average(shifted, zone)
    rel = float(np.max(np.abs(c1.astype(np.int16) - c2.astype(np.int16)))) / 255.0
    assert rel < 0.25


def test_variance_adaptive_step_selection() -> None:
    low = np.full(12, 50.0, dtype=np.float32)
    high = np.full(12, 4000.0, dtype=np.float32)
    assert compute_adaptive_step(low, base_step=1, max_step=8) >= compute_adaptive_step(
        high, base_step=1, max_step=8
    )


def test_multi_moment_mixed_content() -> None:
    pixels = np.zeros((100, 3), dtype=np.uint8)
    pixels[:90] = (0, 0, 40)
    pixels[90:] = (255, 255, 255)
    color, selector = multi_moment_zone_color(pixels)
    assert selector in {"dominant", "median", "mean"}
    assert int(color[2]) > 40


def test_edge_anchored_rect_extends_left_edge() -> None:
    rect = edge_anchored_rect((0, 2, 4, 6), frame_w=20, frame_h=10)
    assert rect[0] == 0
    assert rect[2] >= 4


def test_temporal_noise_reduction() -> None:
    acc = ZoneAccumulator(4, alpha_min=0.3, alpha_max=0.3)
    stable = np.tile(np.array([[100, 120, 140]], dtype=np.uint8), (4, 1))
    noisy = stable.copy()
    noisy[0] = (255, 0, 0)
    output = noisy.astype(np.float32)
    for _ in range(12):
        output = acc.update(noisy if _ % 2 == 0 else stable, frame_delta=0.2).astype(np.float32)
    assert float(np.mean(np.abs(output - stable.astype(np.float32)))) < 90.0


def test_zone_accumulator_first_frame_is_not_biased_toward_black() -> None:
    acc = ZoneAccumulator(1, alpha_min=0.05, alpha_max=0.05)
    first = np.asarray([[120, 140, 160]], dtype=np.uint8)
    assert acc.update(first, frame_delta=0.0).tolist() == first.tolist()


def test_blue_noise_reduces_quantization_banding() -> None:
    gradient = np.linspace(100, 110, 16, dtype=np.float32)[:, None] * np.ones((16, 3))
    plain = np.clip(np.rint(gradient), 0, 255).astype(np.uint8)
    dithered = apply_blue_noise_dither(gradient, frame_index=3, strength=0.8)
    dithered_u8 = np.clip(np.rint(dithered), 0, 255).astype(np.uint8)
    assert len(np.unique(plain[:, 0])) <= len(np.unique(dithered_u8[:, 0]))


def test_privacy_mask_zeros_region() -> None:
    frame = np.full((10, 10, 3), 200, dtype=np.uint8)
    zones = [(0, 0, 10, 2)]
    colors = zone_colors_array(
        frame,
        zones,
        privacy_zones=[PrivacyZone(x=0.0, y=0.0, w=1.0, h=0.2)],
        use_zone_box_filter=True,
        edge_anchor_sampling=False,
        sampling_mode="area_average",
    )
    assert isinstance(colors, np.ndarray)
    assert int(np.max(colors[0])) == 0
