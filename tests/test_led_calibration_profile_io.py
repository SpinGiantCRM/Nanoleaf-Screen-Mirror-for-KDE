from __future__ import annotations

import json

import pytest

from nanoleaf_sync.config.led_calibration_profile_io import (
    export_measured_led_calibration_profile,
    import_measured_led_calibration_profile,
    led_calibration_profile_from_dict,
    led_calibration_profile_to_dict,
)
from nanoleaf_sync.config.model import LedCalibrationProfile


def test_led_calibration_profile_round_trip_dict() -> None:
    profile = LedCalibrationProfile(red_gain=1.1, blue_gain=0.9, black_luminance_cutoff=0.004)
    restored = led_calibration_profile_from_dict(led_calibration_profile_to_dict(profile))
    assert restored.red_gain == pytest.approx(1.1)
    assert restored.blue_gain == pytest.approx(0.9)
    assert restored.black_luminance_cutoff == pytest.approx(0.004)


def test_export_import_measured_profile_json() -> None:
    profile = LedCalibrationProfile(red_gain=1.05, green_gain=0.95)
    exported = export_measured_led_calibration_profile(profile=profile, display_preset="sdr")
    parsed = json.loads(exported)
    assert parsed["display_preset"] == "sdr"
    preset, restored = import_measured_led_calibration_profile(exported)
    assert preset == "sdr"
    assert restored.red_gain == pytest.approx(1.05)
    assert restored.green_gain == pytest.approx(0.95)


def test_import_rejects_unknown_profile_kind() -> None:
    with pytest.raises(ValueError, match="Unrecognized LED calibration profile"):
        import_measured_led_calibration_profile('{"display_preset":"sdr","profile":{}}')
