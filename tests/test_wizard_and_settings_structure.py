from nanoleaf_sync.ui.calibration_state import CalibrationState


def test_calibration_state_has_minimal_fields() -> None:
    fields = CalibrationState.__dataclass_fields__
    assert "corner_anchor_top_left" in fields
    assert "reverse_zones" in fields
    assert "corner" + "_offsets_enabled" not in fields
