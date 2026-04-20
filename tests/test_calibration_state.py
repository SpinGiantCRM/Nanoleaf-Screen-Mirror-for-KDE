from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    build_latency_result,
    latency_result_summary,
    next_corner_start_anchor,
    should_auto_run_latency_probe,
)


def test_shared_calibration_state_round_trips_core_fields() -> None:
    cfg = AppConfig(device_zone_count=0, zone_offset=3, reverse_zones=True, zone_preset="horizontal")
    state = CalibrationState.from_config(cfg, {"device_zone_count": 18})

    assert state.zone_preset == "horizontal"
    assert state.zone_offset == 3
    assert state.reverse_zones is True
    assert state.auto_device_zone_count is True
    assert state.effective_device_zone_count() == 18


def test_combined_corner_offset_mode_reflects_live_offset_reverse() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=12, zone_offset=0, reverse_zones=False), {})
    base = state.step_for_mode("corner+offset alignment", 0)
    state.zone_offset = 2
    state.reverse_zones = True
    changed = state.step_for_mode("corner+offset alignment", 0)

    assert "offset=+0" in base.label
    assert "reverse=off" in base.label
    assert "offset=+2" in changed.label
    assert "reverse=on" in changed.label


def test_manual_corner_anchor_assignment_guides_corner_steps() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    state.corner_start_anchor = 5
    step = state.step_for_mode("corner+offset alignment", 0)
    assert "#6" in step.label
    assert next_corner_start_anchor(5, device_zone_count=8) == 6


def test_latency_policy_is_predictable_and_manual_vs_auto_labeled() -> None:
    assert should_auto_run_latency_probe(policy="manual", last_result=None, active_backend="kwin-dbus") is False
    assert should_auto_run_latency_probe(policy="on-open", last_result=None, active_backend="kwin-dbus") is True

    result = build_latency_result(backend="kwin-dbus", measured_latency_ms=23.4, triggered_by="manual")
    assert should_auto_run_latency_probe(
        policy="on-open-once-per-backend",
        last_result=result,
        active_backend="kwin-dbus",
    ) is False
    assert should_auto_run_latency_probe(
        policy="on-open-once-per-backend",
        last_result=result,
        active_backend="kmsgrab",
    ) is True
    assert "trigger=manual" in latency_result_summary(result)


def test_testing_step_controls_and_frame_generation_stay_coherent() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=6), {})
    mode = "direction walk"
    assert state.cycle_length(mode) == 6
    frame = state.frame_for_step(mode=mode, step=2, brightness=0.5, all_off_except_active=True)
    assert len(frame) == 6
    assert sum(1 for rgb in frame if rgb != (0, 0, 0)) == 1
