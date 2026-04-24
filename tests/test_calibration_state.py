from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.ui.calibration_state import CalibrationState


def test_calibration_state_uses_reverse_from_calibration_block() -> None:
    cfg = AppConfig(
        calibration=CalibrationConfig(device_zone_count=12, reverse_zones=True),
        zones=[],
    )
    state = CalibrationState.from_config(cfg, {})
    assert state.reverse_zones is True
    assert state.effective_device_zone_count() == 12


def test_calibration_state_keeps_manual_strip_count_when_runtime_reports_different_value() -> None:
    cfg = AppConfig(device_zone_count=48, calibration=CalibrationConfig(device_zone_count=48), zones=[])
    state = CalibrationState.from_config(cfg, {"device_zone_count": 54})
    assert state.device_zone_count == 48
    assert state.zone_count == 48
