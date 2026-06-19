from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.ui.calibration_state import CalibrationState
from nanoleaf_sync.ui.zone_presets import make_horizontal_zones


def test_calibration_state_uses_reverse_from_calibration_block() -> None:
    cfg = AppConfig(
        calibration=CalibrationConfig(device_zone_count=12, reverse_zones=True),
        zones=[],
    )
    state = CalibrationState.from_config(cfg, {})
    assert state.reverse_zones is True
    assert state.effective_device_zone_count() == 12


def test_calibration_state_keeps_manual_strip_count_when_runtime_reports_different_value() -> None:
    cfg = AppConfig(
        device_zone_count=48, calibration=CalibrationConfig(device_zone_count=48), zones=[]
    )
    state = CalibrationState.from_config(cfg, {"device_zone_count": 54})
    assert state.device_zone_count == 48
    assert state.zone_count == 48


def test_calibration_state_ignores_stale_source_zone_count_in_edge_strip_mode() -> None:
    cfg = AppConfig(
        device_zone_count=48,
        layout_preset="edge_strip",
        zones=make_horizontal_zones(8),
        calibration=CalibrationConfig(device_zone_count=48),
    )
    state = CalibrationState.from_config(cfg, {"device_zone_count": 48})
    assert state.zone_count == 48
    assert state.source_zones_user_configured is False
