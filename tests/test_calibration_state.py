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
