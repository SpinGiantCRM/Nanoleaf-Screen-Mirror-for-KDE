import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import _ensure_runtime_artifacts, _mapping_signature, process_frame
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.zone_presets import edge_side_counts


def _cfg_with_valid_calibration(zone_count: int = 48, **kwargs) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
        reverse_zones=bool(kwargs.pop("reverse_zones", False)),
    )
    return AppConfig(device_zone_count=zone_count, calibration=calibration, **kwargs)


def test_mapping_signature_tracks_reverse_and_model() -> None:
    cfg = _cfg_with_valid_calibration(10, calibration_model='corner_anchored', reverse_zones=True)
    sig = _mapping_signature(source_zone_count=10, config=cfg, detected_device_zone_count=10)
    assert sig[0] == 10
    assert isinstance(sig[3], bool)


def test_no_global_zone_offset_reintroduced() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :] = [12, 12, 12]
    frame[:6, :, :] = [255, 0, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48)
    colors = process_frame(frame=frame, prev_smoothed_colors=[], zones_px=zones_px, device_zone_indices=device_zone_indices, brightness=1.0, smoothing=1.0)
    top, right, bottom, _left = edge_side_counts(zone_count=48, width=160, height=90)
    assert sum(1 for c in colors[:top] if c[0] > 120) >= max(1, top - 2)
    assert sum(1 for c in colors[top + right : top + right + bottom] if c[0] > 90) <= 1


def test_tight_locality_keeps_bottom_left_signal_local() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[-8:, :8, :] = [0, 255, 0]

    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip", edge_locality="tight")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48)
    colors = process_frame(frame=frame, prev_smoothed_colors=[], zones_px=zones_px, device_zone_indices=device_zone_indices, brightness=1.0, smoothing=1.0, edge_locality="tight")

    top_n, right_n, bottom_n, left_n = edge_side_counts(zone_count=48, width=160, height=90)
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    left = colors[top_n + right_n + bottom_n : top_n + right_n + bottom_n + left_n]

    assert sum(1 for c in bottom[-4:] if c[1] > 85) >= 1
    assert sum(1 for c in bottom[:4] if c[1] > 60) == 0


def test_wide_locality_is_broader_than_tight_but_not_global() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[-8:, :8, :] = [0, 255, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48)

    tight = process_frame(frame=frame, prev_smoothed_colors=[], zones_px=zones_px, device_zone_indices=device_zone_indices, brightness=1.0, smoothing=1.0, edge_locality="tight")
    wide = process_frame(frame=frame, prev_smoothed_colors=[], zones_px=zones_px, device_zone_indices=device_zone_indices, brightness=1.0, smoothing=1.0, edge_locality="wide")

    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    tight_bottom = tight[top_n + right_n : top_n + right_n + bottom_n]
    wide_bottom = wide[top_n + right_n : top_n + right_n + bottom_n]

    tight_active = sum(1 for c in tight_bottom if c[1] > 60)
    wide_active = sum(1 for c in wide_bottom if c[1] > 60)
    assert wide_active >= tight_active
    assert wide_active < len(wide_bottom)


def test_sampling_quality_does_not_change_layout_geometry() -> None:
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px_a, _ = _ensure_runtime_artifacts(state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48)
    cfg2 = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip", sampling_quality="low")
    state2 = RuntimeState()
    zones_px_b, _ = _ensure_runtime_artifacts(state=state2, config=cfg2, img_w=160, img_h=90, detected_device_zone_count=48)
    assert zones_px_a == zones_px_b


def test_motion_preset_does_not_break_spatial_locality() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:8, -8:, :] = [255, 0, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip", motion_preset="dynamic")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48)
    colors = process_frame(frame=frame, prev_smoothed_colors=[], zones_px=zones_px, device_zone_indices=device_zone_indices, brightness=1.0, smoothing=1.0, motion_preset="dynamic")
    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    top = colors[:top_n]
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    assert sum(1 for c in top[-4:] if c[0] > 85) >= 1
    assert sum(1 for c in bottom if c[0] > 70) <= 1
