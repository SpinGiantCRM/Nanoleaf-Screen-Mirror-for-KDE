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
    assert 'QLabel("Edge locality")' in text
    assert 'QLabel("Motion")' in text
    assert 'QLabel("Color style")' in text
    assert 'QLabel("Screen sampling zones")' in text
    assert "matched to strip LED zones" in text
    assert "self.zone_count_slider" not in text
    assert "_set_group_contents_visible(self.advanced_details_group" in text


def test_wizard_and_settings_use_canonical_preset_vocabulary() -> None:
    wizard = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    settings = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    for token in (
        "layout_preset",
        "edge_locality",
        "sampling_quality",
        "motion_preset",
        "color_style",
        "display_preset",
    ):
        assert token in wizard
        assert token in settings
    for label in ("Layout", "Edge locality", "Quality", "Motion", "Color style"):
        assert label in wizard
        assert label in settings


def test_horizontal_layout_is_not_primary_recommendation() -> None:
    wizard = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    helper = open("src/nanoleaf_sync/ui/preset_ui.py", "r", encoding="utf-8").read()
    assert "Horizontal (diagnostic, not recommended)" not in helper
    assert "layout_debug_combo" not in wizard
    assert "Full-screen horizontal" not in wizard


def test_old_ui_labels_removed_from_primary_flow() -> None:
    wizard = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    settings = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "Dynamism" not in wizard
    assert "Dynamism" not in settings
    assert "Optional vibrancy 100%" not in wizard
    assert "initialized from saved/device metadata" not in wizard
    assert "using reported device zone count" not in wizard.lower()
