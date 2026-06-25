from nanoleaf_sync.ui.calibration_state import CalibrationState
from nanoleaf_sync.ui.layout_helpers import mark_compact, stretch_combo_popup, stretch_menu_width
from nanoleaf_sync.ui.preset_ui import (
    COLOR_STYLE_LABELS,
    EDGE_LOCALITY_LABELS,
    LAYOUT_PRESET_LABELS,
    MOTION_PRESET_LABELS,
    SAMPLING_QUALITY_LABELS,
    labels,
)
from nanoleaf_sync.ui.settings_dialog import SETTINGS_SECTIONS
from tests.qt_headless import (
    group_box_titles,
    label_texts,
    make_display_configurator,
    make_settings_dialog,
)


def test_settings_advanced_runtime_status_collapsed_by_default(monkeypatch) -> None:
    qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    QGroupBox = qt["QGroupBox"]
    runtime_group = next(
        box for box in widget.findChildren(QGroupBox) if box.title() == "Runtime status (technical)"
    )
    assert runtime_group.isCheckable()
    assert runtime_group.isChecked() is False
    assert hasattr(widget, "display_preset_combo")
    mark_compact(qt["QPushButton"]("x"))


def test_layout_helpers_exist() -> None:
    assert callable(stretch_menu_width)
    assert callable(stretch_combo_popup)
    assert callable(mark_compact)


def test_calibration_state_has_minimal_fields() -> None:
    fields = CalibrationState.__dataclass_fields__
    assert "corner_anchor_top_left" in fields
    assert "reverse_zones" in fields
    assert "corner" + "_offsets_enabled" not in fields


def test_step3_look_and_feel_uses_clean_sections_with_collapsed_advanced_details(
    monkeypatch,
) -> None:
    qt, _app, _dialog, widget = make_display_configurator(monkeypatch)
    widget._flow.index = 2
    widget._refresh()
    titles = group_box_titles(widget, qt)
    assert "Appearance" in titles
    assert "Layout" in titles
    assert "Advanced details" in titles
    assert widget.advanced_details_group.isCheckable()
    assert widget.advanced_details_group.isChecked() is False
    section_labels = label_texts(widget, qt)
    assert "Edge locality" in section_labels
    assert "Motion" in section_labels
    assert "Color style" in section_labels
    assert "Screen sampling zones" in section_labels
    assert any("matched to strip LED zones" in text for text in section_labels)
    assert not hasattr(widget, "zone_count_slider")
    assert hasattr(widget, "advanced_details_group")


def test_wizard_and_settings_use_canonical_preset_vocabulary(monkeypatch) -> None:
    qt, _app, _wizard_dialog, wizard = make_display_configurator(monkeypatch)
    _qt2, _app2, _settings_dialog, settings = make_settings_dialog(monkeypatch)

    for combo_name in (
        "edge_locality_combo",
        "motion_preset_combo",
        "color_style_combo",
        "display_preset_combo",
    ):
        assert hasattr(wizard, combo_name)
        assert hasattr(settings, combo_name)

    assert wizard.sampling_quality_combo is not None
    assert settings.sampling_quality_combo is not None

    wizard_labels = (
        labels(EDGE_LOCALITY_LABELS)
        + labels(SAMPLING_QUALITY_LABELS)
        + labels(MOTION_PRESET_LABELS)
        + labels(COLOR_STYLE_LABELS)
    )
    settings_labels = label_texts(settings, qt)
    assert "Layout" in group_box_titles(wizard, qt) or "Layout" in wizard_labels
    assert "Edge locality" in wizard_labels or "Edge locality" in label_texts(wizard, qt)
    assert "Quality" in wizard_labels or any("Quality" in text for text in label_texts(wizard, qt))
    assert "Edge locality" in settings_labels
    assert "Quality" in settings_labels
    assert "Colour style" in settings_labels


def test_horizontal_layout_is_not_primary_recommendation(monkeypatch) -> None:
    _qt, _app, _dialog, wizard = make_display_configurator(monkeypatch)
    layout_labels = [label for label, _value in LAYOUT_PRESET_LABELS]
    assert "Horizontal (diagnostic, not recommended)" not in layout_labels
    assert not hasattr(wizard, "layout_debug_combo")
    assert "Full-screen horizontal" not in " ".join(label_texts(wizard, _qt))


def test_old_ui_labels_removed_from_primary_flow(monkeypatch) -> None:
    qt, _app, _wizard_dialog, wizard = make_display_configurator(monkeypatch)
    _qt2, _app2, _settings_dialog, settings = make_settings_dialog(monkeypatch)
    combined = " ".join(label_texts(wizard, qt) + label_texts(settings, qt))
    assert "Dynamism" not in combined
    assert "Optional vibrancy 100%" not in combined
    assert "initialized from saved/device metadata" not in combined
    assert "using reported device zone count" not in combined.lower()
    assert SETTINGS_SECTIONS == ("Everyday", "Strip setup", "Fine-tuning", "Colour", "Advanced")
