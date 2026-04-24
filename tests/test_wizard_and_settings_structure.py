from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import CORNER_OFFSET_LIMIT, CalibrationState
from nanoleaf_sync.ui.display_configurator import (
    MAX_WIZARD_ZONE_COUNT,
    WIZARD_STEPS,
    WizardFlowState,
    _FallbackGroupBox,
)
from nanoleaf_sync.ui.settings_dialog import MAX_ZONE_COUNT, SETTINGS_SECTIONS


def test_wizard_navigation_and_finish_gating() -> None:
    flow = WizardFlowState(total_steps=len(WIZARD_STEPS), index=0)
    assert flow.step_label() == "Step 1/3: Calibration"
    assert flow.can_go_back() is False
    assert flow.can_go_next() is True

    flow.next()
    flow.next()
    assert flow.step_label() == "Step 3/3: Look & Feel"
    assert flow.can_go_back() is True

    flow.next()
    assert flow.step_label() == "Step 3/3: Look & Feel"
    assert flow.can_go_next() is False


def test_wizard_is_step_driven_and_not_full_settings_dump() -> None:
    assert WIZARD_STEPS == (
        "Calibration",
        "Display Preset",
        "Look & Feel",
    )


def test_zone_range_supports_real_strip_lengths() -> None:
    assert MAX_WIZARD_ZONE_COUNT >= 48
    assert MAX_ZONE_COUNT >= 48
    assert CORNER_OFFSET_LIMIT >= 24


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


def test_wizard_resume_state_defaults_to_empty_payload() -> None:
    cfg = AppConfig()
    assert cfg.wizard_in_progress_state == ""


def test_qgroupbox_fallback_accepts_constructor_args() -> None:
    group = _FallbackGroupBox("Advanced calibration")
    group.setCheckable(True)
    group.setChecked(False)
