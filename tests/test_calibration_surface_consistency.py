from __future__ import annotations

from pathlib import Path


def test_setup_and_settings_surfaces_use_shared_calibration_state() -> None:
    files = [
        Path("src/nanoleaf_sync/ui/display_configurator.py"),
        Path("src/nanoleaf_sync/ui/settings_dialog.py"),
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "CalibrationState" in text
        assert "CalibrationState.from_config" in text


def test_diagnostics_dialog_is_backend_only_without_calibration_controls() -> None:
    text = Path("src/nanoleaf_sync/ui/diagnostics_dialog.py").read_text(encoding="utf-8")
    assert "backend_selection_info" in text
    assert "CalibrationState" not in text
    assert "Run latency checker" not in text


def test_core_calibration_defaults_do_not_drift() -> None:
    model_text = Path("src/nanoleaf_sync/config/model.py").read_text(encoding="utf-8")
    assert "zone_offset: int = 0" in model_text
    assert "reverse_zones: bool = False" in model_text
    assert "device_zone_count: int = 0" in model_text
    assert "corner_offsets_enabled: bool = False" in model_text
