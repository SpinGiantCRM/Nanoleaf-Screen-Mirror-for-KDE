from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, LedCalibrationProfile
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.runtime.engine import (
    _resolve_capture_frame_dimensions,
    run_loop,
)
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.service import NanoleafSyncService


def _cfg_with_valid_calibration(zone_count: int = 48, **kwargs) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
    )
    return AppConfig(device_zone_count=zone_count, calibration=calibration, **kwargs)


def test_validate_config_preserves_advanced_fields() -> None:
    matrix = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    cfg = AppConfig(
        display_gamut="dci-p3",
        accuracy_mode=True,
        live_diagnostics_enabled=True,
        auto_turn_on=False,
        startup_frame_timeout_s=12.5,
        stale_frame_drop_enabled=False,
        max_send_age_frame_budget_multiplier=3.0,
        min_max_send_age_ms=80.0,
        allow_zone_count_override=True,
        wizard_state_version=2,
        led_calibration_profile_sdr=LedCalibrationProfile(color_matrix=list(matrix)),
    )
    result = validate_config(cfg)
    assert result.display_gamut == "dci-p3"
    assert result.accuracy_mode is True
    assert result.live_diagnostics_enabled is True
    assert result.auto_turn_on is False
    assert result.startup_frame_timeout_s == pytest.approx(12.5)
    assert result.stale_frame_drop_enabled is False
    assert result.max_send_age_frame_budget_multiplier == pytest.approx(3.0)
    assert result.min_max_send_age_ms == pytest.approx(80.0)
    assert result.allow_zone_count_override is True
    assert result.wizard_state_version == 2
    assert result.led_calibration_profile_sdr.color_matrix == matrix


def test_validate_config_roundtrip_through_store(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path)
    cfg = validate_config(
        AppConfig(
            fps=45,
            display_gamut="bt.2020",
            live_diagnostics_enabled=True,
            allow_zone_count_override=True,
            led_calibration_profile_hdr=LedCalibrationProfile(
                color_matrix=[1.1, 0.0, 0.0, 0.0, 0.9, 0.0, 0.0, 0.0, 1.2]
            ),
        )
    )
    mgr.save(cfg)
    loaded = mgr.load()
    assert loaded.fps == 45
    assert loaded.display_gamut == "bt.2020"
    assert loaded.live_diagnostics_enabled is True
    assert loaded.allow_zone_count_override is True
    assert loaded.led_calibration_profile_hdr.color_matrix == pytest.approx(
        [1.1, 0.0, 0.0, 0.0, 0.9, 0.0, 0.0, 0.0, 1.2]
    )


def test_config_manager_recovers_from_invalid_raw_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("device_zone_count = 99999\n", encoding="utf-8")
    mgr = ConfigManager(path)
    loaded = mgr.load()
    assert loaded.device_zone_count == 0
    assert path.with_suffix(path.suffix + ".invalid").exists()


def test_make_device_driver_propagates_live_write_optimization_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {}

    class _Driver:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "nanoleaf_sync.service.NanoleafUSBDriver",
        _Driver,
    )
    svc = NanoleafSyncService(config=_cfg_with_valid_calibration(48))
    svc.make_device_driver(enable_live_frame_write_optimization=False)
    assert captured["enable_live_frame_write_optimization"] is False


def test_precomputed_capture_uses_backend_display_dimensions() -> None:
    class _Params:
        width = 3840
        height = 2160

    class _Backend:
        params = _Params()

    precomputed = np.zeros((60, 3), dtype=np.uint8)
    width, height = _resolve_capture_frame_dimensions(
        frame=None,
        precomputed=precomputed,
        capture_backend=_Backend(),
        fallback_width=0,
        fallback_height=0,
    )
    assert width == 3840
    assert height == 2160
    assert precomputed.shape == (60, 3)


def test_output_session_generation_blocks_stale_writer() -> None:
    controller = OutputSessionController()
    old_generation = controller.begin_mirroring_generation()
    active_generation = controller.begin_mirroring_generation()
    assert controller.can_mirroring_write(old_generation) is False
    assert controller.can_mirroring_write(active_generation) is True
    controller.revoke_mirroring_generation(active_generation)
    assert controller.can_mirroring_write(active_generation) is False


def test_run_loop_records_output_owner_drops() -> None:
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

        def send_frame_with_timing(self, _colors):
            return {"device_write_ms": 1.0}

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)

    def _stop_soon() -> None:
        time.sleep(0.25)
        state.stop_event.set()

    threading.Thread(target=_stop_soon, daemon=True).start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _CountingDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
        can_mirroring_write=lambda: False,
    )
    assert state.output_owner_dropped_frames >= 1


def test_flattening_mitigation_independent_of_live_diagnostics() -> None:
    from nanoleaf_sync.runtime.engine import _side_variance_diagnostics

    sampled = np.array(
        [
            [200, 10, 10],
            [210, 12, 12],
            [5, 5, 5],
            [6, 6, 6],
        ],
        dtype=np.uint8,
    )
    final = np.array(
        [
            [80, 80, 80],
            [82, 82, 82],
            [5, 5, 5],
            [6, 6, 6],
        ],
        dtype=np.uint8,
    )
    side_var = _side_variance_diagnostics(
        sampled=sampled,
        final=final,
        side_counts=(2, 2, 0, 0),
    )
    assert any(bool(side.get("processing_flattened", False)) for side in side_var.values())


def test_service_start_uses_configured_startup_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    class _Lifecycle:
        def start(self, *, startup_timeout_s: float = 1.0) -> bool:
            captured["startup_timeout_s"] = startup_timeout_s
            return True

    svc = NanoleafSyncService(config=_cfg_with_valid_calibration(48, startup_frame_timeout_s=9.0))
    svc._lifecycle = _Lifecycle()  # type: ignore[attr-defined]
    svc.start()
    assert captured["startup_timeout_s"] == pytest.approx(9.0)
