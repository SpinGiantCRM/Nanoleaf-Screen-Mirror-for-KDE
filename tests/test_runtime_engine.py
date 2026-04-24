import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import _ensure_runtime_artifacts, _mapping_signature, process_frame
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.zone_presets import edge_side_counts


def test_mapping_signature_tracks_reverse_and_model() -> None:
    cfg = AppConfig(
        device_zone_count=10,
        calibration_model='corner_anchored',
        calibration=CalibrationConfig(reverse_zones=True),
    )
    sig = _mapping_signature(source_zone_count=10, config=cfg, detected_device_zone_count=10)
    assert sig[0] == 10
    assert isinstance(sig[4], bool)


def test_process_frame_edge_colors_follow_continuous_perimeter_order() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:6, :, :] = np.array([255, 0, 0], dtype=np.uint8)  # top red
    frame[:, -6:, :] = np.array([0, 255, 0], dtype=np.uint8)  # right green
    frame[-6:, :, :] = np.array([0, 0, 255], dtype=np.uint8)  # bottom blue
    frame[:, :6, :] = np.array([255, 255, 255], dtype=np.uint8)  # left white

    cfg = AppConfig(zones=[], zone_preset="edge-weighted", device_zone_count=48)
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top, right, bottom, left = edge_side_counts(zone_count=48, width=160, height=90)
    top_run = colors[:top]
    right_run = colors[top : top + right]
    bottom_run = colors[top + right : top + right + bottom]
    left_run = colors[top + right + bottom :]
    assert sum(1 for c in top_run if c[0] > c[1] and c[0] > c[2]) >= len(top_run) - 2
    assert sum(1 for c in right_run if c[1] > c[0] and c[1] > c[2]) >= len(right_run) - 2
    assert sum(1 for c in bottom_run if c[2] > c[0] and c[2] > c[1]) >= len(bottom_run) - 2
    assert sum(1 for c in left_run if abs(c[0] - c[1]) <= 20 and abs(c[1] - c[2]) <= 20) >= len(left_run) - 2


def test_edge_weighted_sampling_avoids_global_average_behavior() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :] = np.array([20, 20, 20], dtype=np.uint8)
    frame[:6, :, :] = np.array([255, 0, 0], dtype=np.uint8)

    cfg = AppConfig(zones=[], zone_preset="edge-weighted", device_zone_count=48)
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    top = colors[:top_n]
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    assert all(c[0] > 150 for c in top)
    assert all(c[0] < 80 for c in bottom)


def test_edge_weighted_corner_signal_stays_localized_bottom_left() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[-10:, :10, :] = np.array([0, 255, 0], dtype=np.uint8)

    cfg = AppConfig(zones=[], zone_preset="edge-weighted", device_zone_count=48)
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top_n, right_n, bottom_n, left_n = edge_side_counts(zone_count=48, width=160, height=90)
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    left = colors[top_n + right_n + bottom_n : top_n + right_n + bottom_n + left_n]

    # Bottom side is ordered right -> left. Left side is ordered bottom -> top.
    assert sum(1 for c in bottom[-4:] if c[1] > 85) >= 1
    assert sum(1 for c in bottom[:4] if c[1] > 60) <= 1
    assert sum(1 for c in left[:4] if c[1] > 85) >= 1
    assert sum(1 for c in left[-4:] if c[1] > 60) <= 1


def test_edge_weighted_corner_signal_stays_localized_top_right() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:10, -10:, :] = np.array([255, 0, 0], dtype=np.uint8)

    cfg = AppConfig(zones=[], zone_preset="edge-weighted", device_zone_count=48)
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    top = colors[:top_n]
    right = colors[top_n : top_n + right_n]
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]

    assert sum(1 for c in top[-4:] if c[0] > 85) >= 1
    assert sum(1 for c in top[:4] if c[0] > 60) <= 1
    assert sum(1 for c in right[:4] if c[0] > 85) >= 1
    assert sum(1 for c in bottom if c[0] > 70) <= 1


def test_edge_weighted_sampling_handles_different_edge_colors_without_full_side_smear() -> None:
    frame = np.zeros((100, 180, 3), dtype=np.uint8)
    frame[:8, 70:110, :] = np.array([255, 0, 0], dtype=np.uint8)      # top center red
    frame[30:70, -8:, :] = np.array([0, 255, 0], dtype=np.uint8)      # right center green
    frame[-8:, 70:110, :] = np.array([0, 0, 255], dtype=np.uint8)     # bottom center blue
    frame[30:70, :8, :] = np.array([255, 255, 255], dtype=np.uint8)   # left center white

    cfg = AppConfig(zones=[], zone_preset="edge-weighted", device_zone_count=48)
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=180,
        img_h=100,
        detected_device_zone_count=48,
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=180, height=100)
    top = colors[:top_n]
    right = colors[top_n : top_n + right_n]
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]

    top_red = sum(1 for c in top if c[0] > c[1] and c[0] > c[2] and c[0] > 100)
    bottom_blue = sum(1 for c in bottom if c[2] > c[0] and c[2] > c[1] and c[2] > 100)
    right_green = sum(1 for c in right if c[1] > c[0] and c[1] > c[2] and c[1] > 70)
    assert 1 <= top_red <= max(4, top_n // 2)
    assert 1 <= bottom_blue <= max(4, bottom_n // 2)
    assert 1 <= right_green <= max(4, right_n // 2)
