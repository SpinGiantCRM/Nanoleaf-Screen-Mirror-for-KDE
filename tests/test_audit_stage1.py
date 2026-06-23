from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.calibration_resolver import (
    DEVICE_ZONE_MISMATCH_STATUS,
    evaluate_device_zone_authority,
)
from nanoleaf_sync.runtime.engine import (
    compute_max_send_age_ms,
    evaluate_stale_output_drop,
    run_loop,
)
from nanoleaf_sync.runtime.state import RuntimeState


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


def test_compute_max_send_age_ms_uses_minimum_floor() -> None:
    assert compute_max_send_age_ms(target_fps=120.0) == 60.0


def test_compute_max_send_age_ms_scales_with_low_fps() -> None:
    value = compute_max_send_age_ms(
        target_fps=15.0,
        min_max_send_age_ms=40.0,
        budget_multiplier=2.0,
    )
    assert value == pytest.approx(133.333, rel=0.01)


def test_evaluate_stale_output_drop_drops_old_frames() -> None:
    should_drop, age_ms, max_age_ms, reason = evaluate_stale_output_drop(
        captured_at=10.0,
        now=10.1,
        target_fps=60.0,
        stale_frame_drop_enabled=True,
        min_max_send_age_ms=60.0,
        max_send_age_frame_budget_multiplier=2.0,
    )
    assert should_drop is True
    assert age_ms == pytest.approx(100.0)
    assert max_age_ms == 60.0
    assert "frame_age_ms=" in reason


def test_evaluate_stale_output_drop_allows_fresh_frames() -> None:
    should_drop, age_ms, max_age_ms, _reason = evaluate_stale_output_drop(
        captured_at=10.0,
        now=10.01,
        target_fps=30.0,
        stale_frame_drop_enabled=True,
        min_max_send_age_ms=60.0,
        max_send_age_frame_budget_multiplier=2.0,
    )
    assert should_drop is False
    assert age_ms == pytest.approx(10.0)
    assert max_age_ms == pytest.approx(66.667, rel=0.01)


def test_zone_mismatch_blocks_authority_without_override() -> None:
    cfg = _cfg_with_valid_calibration(80)
    authority = evaluate_device_zone_authority(config=cfg, detected_device_zone_count=75)
    assert authority.blocked is True
    assert authority.status == DEVICE_ZONE_MISMATCH_STATUS
    assert authority.mapping_repair_required is True


def test_zone_mismatch_allows_override() -> None:
    cfg = _cfg_with_valid_calibration(80, allow_zone_count_override=True)
    authority = evaluate_device_zone_authority(config=cfg, detected_device_zone_count=75)
    assert authority.blocked is False
    assert authority.override_active is True


def test_kwin_no_monitor_uses_capture_active_screen() -> None:
    backend = KWinDBusScreenshotCapture(width=480, height=270, monitor_id="")
    attempts = backend._screenshot2_method_attempts()
    assert len(attempts) == 1
    assert attempts[0][0] == "CaptureActiveScreen"
    assert attempts[0][1] == "a{sv}h"
    backend.close()


def test_run_loop_drops_stale_frame_before_hid_send(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FastCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [30, 40, 50]
            return frame

    class _CountingDriver:
        reported_zone_count = 48
        zone_count = 48
        sends = 0

        def send_frame_with_timing(self, _colors):
            self.sends += 1
            return {"device_write_ms": 1.0, "live_send_policy": "response_required"}

    driver = _CountingDriver()
    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)

    monkeypatch.setattr(
        "nanoleaf_sync.runtime.engine.evaluate_stale_output_drop",
        lambda **_kwargs: (True, 120.0, 60.0, "forced-stale"),
    )

    stopper = threading.Thread(
        target=lambda: (time.sleep(0.2), state.stop_event.set()),
        daemon=True,
    )
    stopper.start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: driver,
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert driver.sends == 0
    assert state.stale_output_dropped_frames >= 1
    assert state.frames_sent == 0
    assert state.prev_sent_colors == []


def test_run_loop_sends_fresh_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FastCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [30, 40, 50]
            return frame

    class _CountingDriver:
        reported_zone_count = 48
        zone_count = 48
        sends = 0

        def send_frame_with_timing(self, _colors):
            self.sends += 1
            return {"device_write_ms": 1.0, "live_send_policy": "response_required"}

    driver = _CountingDriver()
    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)

    monkeypatch.setattr(
        "nanoleaf_sync.runtime.engine.evaluate_stale_output_drop",
        lambda **_kwargs: (False, 5.0, 60.0, ""),
    )

    def _stop_after_first_send_or_timeout() -> None:
        deadline = time.perf_counter() + 0.5
        while time.perf_counter() < deadline and not state.first_frame_sent:
            time.sleep(0.005)
        state.stop_event.set()

    stopper = threading.Thread(target=_stop_after_first_send_or_timeout, daemon=True)
    stopper.start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: driver,
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert driver.sends >= 1
    assert state.frames_sent >= 1


def test_run_loop_skips_duplicate_unchanged_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_audit_stage1 import _cfg_with_valid_calibration

    class _StaticCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [30, 40, 50]
            return frame

    class _CountingDriver:
        reported_zone_count = 48
        zone_count = 48
        sends = 0

        def send_frame_with_timing(self, _colors):
            self.sends += 1
            return {"device_write_ms": 1.0, "live_send_policy": "response_required"}

    driver = _CountingDriver()
    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)

    def _stop_after_duplicate_skip() -> None:
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and state.duplicate_output_skipped_frames < 1:
            time.sleep(0.01)
        state.stop_event.set()

    stopper = threading.Thread(target=_stop_after_duplicate_skip, daemon=True)
    stopper.start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _StaticCapture(),
        get_driver=lambda: driver,
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert driver.sends >= 1
    assert state.duplicate_output_skipped_frames >= 1


def test_run_loop_zone_mismatch_blocks_startup() -> None:
    class _FastCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [30, 40, 50]
            return frame

    class _MismatchDriver:
        reported_zone_count = 75
        zone_count = 75

        def send_frame_with_timing(self, _colors):
            return {"device_write_ms": 1.0}

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(80, fps=30)

    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _MismatchDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert state.calibration_status == DEVICE_ZONE_MISMATCH_STATUS
    assert state.frames_sent == 0
    assert state.mapping_repair_required is True


def test_service_startup_blocks_on_zone_mismatch() -> None:
    from tests.test_service_status_modes import FakeCapture

    class _MismatchDriver:
        reported_zone_count = 75
        zone_count = 75

        def initialize(self) -> None:
            return None

        def close(self) -> None:
            return None

    from nanoleaf_sync.service import NanoleafSyncService

    cfg = _cfg_with_valid_calibration(80, fps=30, use_mock_capture=False)
    svc = NanoleafSyncService(
        config=cfg,
        capture_backend_override=FakeCapture(name="kwin-dbus"),
        driver_override=_MismatchDriver(),
    )
    started = svc.start()
    time.sleep(0.15)
    assert started is False
    status = svc.get_status()
    assert status.get("mapping_repair_required") is True
    assert status.get("device_zone_count_mismatch") is True
