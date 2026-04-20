from __future__ import annotations

from pathlib import Path


def test_setup_settings_and_testing_surfaces_use_shared_calibration_state() -> None:
    files = [
        Path("src/nanoleaf_sync/ui/display_configurator.py"),
        Path("src/nanoleaf_sync/ui/settings_dialog.py"),
        Path("src/nanoleaf_sync/ui/diagnostics_dialog.py"),
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "CalibrationState" in text
        assert "calibration_state" in text


def test_core_calibration_defaults_do_not_drift() -> None:
    model_text = Path("src/nanoleaf_sync/config/model.py").read_text(encoding="utf-8")
    assert "zone_offset: int = 0" in model_text
    assert "reverse_zones: bool = False" in model_text
    assert "device_zone_count: int = 0" in model_text
    assert "corner_offsets_enabled: bool = False" in model_text
