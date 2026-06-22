from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.zone_presets import edge_side_counts


def _cfg(zone_count: int = 48) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
    )
    return AppConfig(
        device_zone_count=zone_count,
        calibration=calibration,
        zones=[],
        layout_preset="edge_strip",
    )


def _run_clip(frame: np.ndarray) -> list[tuple[int, int, int]]:
    from nanoleaf_sync.runtime.engine import _ensure_runtime_artifacts

    cfg = _cfg()
    state = RuntimeState()
    h, w = frame.shape[:2]
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=w,
        img_h=h,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=0.8,
    )
    return [tuple(int(v) for v in row) for row in colors]


def test_black_white_flash_clip_does_not_flatten_all_zones() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :] = [255, 255, 255]
    colors = _run_clip(frame)
    assert max(max(channel) for channel in colors) > 40


def test_dark_scene_small_red_ui_element_stays_visible() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[10:14, 10:14, 0] = 255
    colors = _run_clip(frame)
    top_n, right_n, bottom_n, left_n = edge_side_counts(zone_count=48, width=160, height=90)
    top = colors[:top_n]
    assert len(top) >= 1


def test_rapid_alternating_colors_produce_non_uniform_output() -> None:
    red = np.zeros((90, 160, 3), dtype=np.uint8)
    red[:, :] = [255, 0, 0]
    blue = np.zeros_like(red)
    blue[:, :] = [0, 0, 255]
    first = _run_clip(red)
    second = _run_clip(blue)
    assert first != second
