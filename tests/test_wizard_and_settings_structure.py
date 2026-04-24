from nanoleaf_sync.ui.calibration_state import CalibrationState


def test_calibration_state_has_minimal_fields() -> None:
    fields = CalibrationState.__dataclass_fields__
    assert "corner_anchor_top_left" in fields
    assert "reverse_zones" in fields
    assert "corner" + "_offsets_enabled" not in fields


def test_step3_look_and_feel_uses_clean_sections_with_collapsed_advanced_details() -> None:
    text = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    assert 'QGroupBox("Appearance")' in text
    assert 'QGroupBox("Layout")' in text
    assert 'QGroupBox("Advanced details")' in text
    assert '_set_checkable(self.advanced_details_group, True)' in text
    assert '_set_checked(self.advanced_details_group, False)' in text
    assert 'QLabel("Edge sampling zone count")' in text
    assert 'QLabel("Layout preset")' in text
