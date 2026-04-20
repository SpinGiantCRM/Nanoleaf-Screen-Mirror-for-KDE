from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import CalibrationState
from nanoleaf_sync.ui.display_configurator import MAX_WIZARD_ZONE_COUNT, WIZARD_STEPS, WizardFlowState
from nanoleaf_sync.ui.settings_dialog import MAX_ZONE_COUNT, SETTINGS_SECTIONS


def test_wizard_navigation_and_finish_gating() -> None:
    flow = WizardFlowState(total_steps=len(WIZARD_STEPS), index=0)
    assert flow.step_label() == "Step 1/5: Welcome & Display"
    assert flow.can_go_back() is False
    assert flow.can_go_next() is True

    flow.next()
    flow.next()
    assert flow.step_label() == "Step 3/5: Zone Basics"
    assert flow.can_go_back() is True

    flow.next()
    flow.next()
    assert flow.step_label() == "Step 5/5: Review & Finish"
    assert flow.can_go_next() is False


def test_wizard_is_step_driven_and_not_full_settings_dump() -> None:
    assert WIZARD_STEPS == (
        "Welcome & Display",
        "Color & HDR",
        "Zone Basics",
        "Calibration Check",
        "Review & Finish",
    )


def test_zone_range_supports_real_strip_lengths() -> None:
    assert MAX_WIZARD_ZONE_COUNT >= 48
    assert MAX_ZONE_COUNT >= 48


def test_settings_dialog_has_grouped_sections_for_scrollable_layout() -> None:
    assert SETTINGS_SECTIONS == (
        "Backend & Diagnostics",
        "Display & Color",
        "Runtime & Performance",
        "Zone Mapping",
        "Calibration & Testing",
        "Output & Startup",
    )


def test_setup_and_settings_share_zone_preset_default() -> None:
    cfg = AppConfig()
    state = CalibrationState.from_config(cfg, runtime_status={})
    assert cfg.zone_preset == "edge-weighted"
    assert state.zone_preset == cfg.zone_preset
