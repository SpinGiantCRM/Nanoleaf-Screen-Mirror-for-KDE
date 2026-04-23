from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.normalize import migrate_config_dict, validate_config
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping_from_config
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.calibration_state import CalibrationState


class _SingleFrameCapture:
    name = "fake-capture"
    last_capture_path = "test"

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def capture(self) -> np.ndarray:
        return self._frame


class _CollectingDriver:
    def __init__(self, stop_event) -> None:
        self.sent_frames = []
        self._stop_event = stop_event

    def send_frame(self, colors):
        self.sent_frames.append(list(colors))
        self._stop_event.set()


def test_full_pipeline_zone_map_brightness_smoothing_and_send() -> None:
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[:, :2] = [200, 0, 0]   # left zone
    frame[:, 2:] = [0, 100, 0]   # right zone

    cfg = AppConfig(
        fps=30,
        brightness=0.5,
        smoothing=0.25,
        zones=[
            ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0),
        ],
        device_zone_count=2,
        zone_offset=1,
        use_mock_capture=False,
        verbose=False,
        color_mode="balanced",
    )

    state = RuntimeState()
    state.prev_smoothed_colors = [(0, 0, 0), (40, 40, 40)]

    capture = _SingleFrameCapture(frame)
    driver = _CollectingDriver(state.stop_event)

    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: capture,
        get_driver=lambda: driver,
        install_drivers=lambda: None,
        close_backends=lambda: None,
    )

    assert len(driver.sent_frames) == 1
    result = driver.sent_frames[0]

    # Zone 0 maps to right zone (zone_offset=1): green (0, ~100, 0) × 0.5 brightness.
    # With adaptive smoothing at defaults, this should move clearly toward current.
    r0, g0, b0 = result[0]
    assert r0 == 0
    assert 10 <= g0 <= 20
    assert b0 == 0

    # Zone 1 maps to left zone: red (~200, 0, 0) × 0.5 brightness vs prev (40, 40, 40).
    # Adaptive smoothing should push R upward strongly, while G/B decay toward zero.
    r1, g1, b1 = result[1]
    assert 50 <= r1 <= 80
    assert 20 <= g1 <= 35
    assert 20 <= b1 <= 35


def test_preview_and_runtime_share_identical_resolved_mapping_snapshot() -> None:
    frame = np.array(
        [[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]]],
        dtype=np.uint8,
    )
    cfg = AppConfig(
        fps=30,
        brightness=1.0,
        smoothing=1.0,
        zones=[
            ZoneConfig(x=0.0, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.25, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.75, y=0.0, w=0.25, h=1.0),
        ],
        device_zone_count=4,
        zone_offset=1,
        use_mock_capture=False,
        verbose=False,
        calibration_model="corner_anchored",
        corner_anchor_top_left=1,
        corner_anchor_top_right=2,
        corner_anchor_bottom_right=3,
        corner_anchor_bottom_left=0,
    )

    preview_state = CalibrationState.from_config(cfg)
    preview_snapshot = preview_state.resolved_mapping_snapshot()
    runtime_snapshot = resolve_calibration_mapping_from_config(
        config=cfg,
        source_zone_count=len(cfg.zones),
    )
    assert preview_snapshot.device_to_source_indices == runtime_snapshot.device_to_source_indices
    assert preview_snapshot.mode == runtime_snapshot.mode
    assert preview_snapshot.direction == runtime_snapshot.direction
    assert preview_snapshot.validation_warnings == runtime_snapshot.validation_warnings

    expected_mapping = [
        preview_state.step_for_mode("direction walk", step).source_zone_index
        for step in range(preview_state.effective_device_zone_count())
    ]

    state = RuntimeState()
    capture = _SingleFrameCapture(frame)
    driver = _CollectingDriver(state.stop_event)

    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: capture,
        get_driver=lambda: driver,
        install_drivers=lambda: None,
        close_backends=lambda: None,
    )

    assert len(driver.sent_frames) == 1
    sent = driver.sent_frames[0]
    source_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    assert sent == [source_colors[idx] for idx in expected_mapping]


def test_migrated_legacy_calibration_config_keeps_preview_runtime_mapping_parity() -> None:
    legacy = {
        "device_zone_count": 8,
        "zones": [
            ZoneConfig(x=0.0, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.25, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.75, y=0.0, w=0.25, h=1.0),
        ],
        "calibration_model": "corner_anchored",
        "corner_anchor_top_left": 0,
        "corner_anchor_top_right": 2,
        "corner_anchor_bottom_right": 4,
        "corner_anchor_bottom_left": 6,
        "zone_offset": -3,
        "reverse_zones": True,
    }
    migrated = migrate_config_dict(legacy)
    cfg = validate_config(AppConfig(**migrated))

    preview_snapshot = CalibrationState.from_config(cfg).resolved_mapping_snapshot()
    runtime_snapshot = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=len(cfg.zones))

    assert migrated["calibration"]["calibration_model"] == "corner_anchored"
    assert preview_snapshot.device_to_source_indices == runtime_snapshot.device_to_source_indices
    assert preview_snapshot.validation_warnings == runtime_snapshot.validation_warnings


def test_manual_explicit_model_is_coerced_to_corner_anchored() -> None:
    cfg = validate_config(
        AppConfig(
            zones=[
                ZoneConfig(x=0.0, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.25, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.5, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.75, y=0.0, w=0.25, h=1.0),
            ],
            device_zone_count=4,
            calibration_model="manual_explicit_map",
            manual_mapping_enabled=False,
            explicit_zone_map=[3, 1, 0, 2],
        )
    )

    preview_snapshot = CalibrationState.from_config(cfg).resolved_mapping_snapshot()
    runtime_snapshot = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=len(cfg.zones))

    assert cfg.calibration_model == "corner_anchored"
    assert cfg.calibration.calibration_model == "corner_anchored"
    assert preview_snapshot.mode == "corner_anchored"
    assert runtime_snapshot.mode == "corner_anchored"


def test_corner_anchored_invalid_anchors_emit_fallback_indicator_and_warning_codes() -> None:
    cfg = validate_config(
        AppConfig(
            zones=[
                ZoneConfig(x=0.0, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.25, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.5, y=0.0, w=0.25, h=1.0),
                ZoneConfig(x=0.75, y=0.0, w=0.25, h=1.0),
            ],
            device_zone_count=8,
            calibration_model="corner_anchored",
            zone_offset=2,
            reverse_zones=True,
            corner_anchor_top_left=1,
            corner_anchor_top_right=1,
            corner_anchor_bottom_right=-1,
            corner_anchor_bottom_left=3,
        )
    )
    snapshot = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=len(cfg.zones))

    assert snapshot.calibration_model == "corner_anchored"
    assert snapshot.strategy == "corner_anchored"
    assert snapshot.fallback_strategy == "deterministic_anchor_inference"
    assert snapshot.invalid_corner_anchor_fallback_active is True
    assert "CORNER_ANCHOR_MISSING" in snapshot.warning_codes
    assert "CORNER_ANCHOR_DUPLICATE" in snapshot.warning_codes
