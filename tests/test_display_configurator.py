from __future__ import annotations

import types

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog, WIZARD_SESSION_ENV


def _qt_stub() -> dict[str, object]:
    class _DummySignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            for callback in self._callbacks:
                try:
                    callback(*args, **kwargs)
                except TypeError:
                    callback()

    class _Dialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, _parent=None):
            self._resize = None

        def setWindowTitle(self, _title):
            pass

        def setLayout(self, _layout):
            pass
        def resize(self, _w, _h):
            self._resize = (_w, _h)

        def accept(self):
            return None

        def reject(self):
            return None

        def exec(self):
            return 1

    class _Slider:
        def __init__(self, _orientation):
            self._value = 0
            self._enabled = True
            self.valueChanged = _DummySignal()

        def setRange(self, _min, _max):
            pass

        def setValue(self, value):
            self._value = value
            self.valueChanged.emit(value)

        def value(self):
            return self._value

        def maximum(self):
            return 10000

        def setEnabled(self, _enabled):
            self._enabled = bool(_enabled)

        def setVisible(self, _visible):
            pass

    class _Combo:
        def __init__(self):
            self._items = []
            self._index = 0
            self.currentIndexChanged = _DummySignal()

        def addItems(self, items):
            self._items.extend(items)

        def findText(self, value):
            try:
                return self._items.index(value)
            except ValueError:
                return -1

        def setCurrentIndex(self, idx):
            self._index = idx
            self.currentIndexChanged.emit(idx)

        def currentText(self):
            return self._items[self._index]

        def setToolTip(self, _text):
            pass

        def setVisible(self, _visible):
            pass

    class _Check:
        def __init__(self, _label):
            self._checked = False
            self.stateChanged = _DummySignal()

        def setChecked(self, checked):
            self._checked = bool(checked)
            self.stateChanged.emit(int(self._checked))

        def isChecked(self):
            return self._checked

        def setVisible(self, _visible):
            pass

    class _Label:
        def __init__(self, _text=""):
            self._text = _text

        def setText(self, text):
            self._text = text

        def setEnabled(self, _enabled):
            pass

        def setVisible(self, _visible):
            pass

    class _Button:
        def __init__(self, _text):
            self.clicked = _DummySignal()
            self._enabled = True

        def setEnabled(self, enabled):
            self._enabled = bool(enabled)

    class _Layout:
        def addWidget(self, *_args):
            pass

        def addLayout(self, *_args):
            pass

        def setRowStretch(self, *_args):
            pass

        def addStretch(self, *_args):
            pass

    return {
        "QDialog": _Dialog,
        "QLabel": _Label,
        "QVBoxLayout": _Layout,
        "QGridLayout": _Layout,
        "QComboBox": _Combo,
        "QSlider": _Slider,
        "QPushButton": _Button,
        "QCheckBox": _Check,
        "Qt": types.SimpleNamespace(Orientation=types.SimpleNamespace(Horizontal=1)),
    }


@pytest.fixture(autouse=True)
def _session_storage_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(WIZARD_SESSION_ENV, str(tmp_path / "wizard-session.json"))


def test_display_configurator_marks_wizard_complete_and_saves_calibration(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(wizard_completed=False, zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog.zone_count_slider.setValue(6)
    high_idx = dialog._dialog.sampling_quality_combo.findText("High")
    dialog._dialog.sampling_quality_combo.setCurrentIndex(high_idx)
    dialog._dialog.zone_offset_slider.setValue(2)
    dialog._dialog.reverse_checkbox.setChecked(True)

    updated = dialog.updated_config()
    assert updated.wizard_completed is True
    assert len(updated.zones) == 6
    assert updated.sampling_quality == "high"
    assert updated.zone_offset == 2
    assert updated.reverse_zones is True


def test_display_configurator_does_not_mutate_wizard_flag_until_saved(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(wizard_completed=False, zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    assert cfg.wizard_completed is False
    assert dialog.updated_config().wizard_completed is True


def test_display_configurator_can_send_real_calibration_pattern(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    sent = {"colors": []}

    def _sender(colors):
        sent["colors"].append(colors)

    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]), calibration_sender=_sender)
    dialog._dialog.calibration_send_button.clicked.emit()
    assert len(sent["colors"]) == 2
    assert any(rgb != (0, 0, 0) for rgb in sent["colors"][-1])


def test_display_configurator_uses_step_1_device_zone_count_for_calibration_frames(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    sent = {"colors": []}

    def _sender(colors):
        sent["colors"].append(colors)

    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]), calibration_sender=_sender)
    dialog._dialog.device_zone_count_slider.setValue(48)
    dialog._dialog.calibration_send_button.clicked.emit()

    assert len(sent["colors"]) == 2
    off_frame, active_frame = sent["colors"]
    assert len(off_frame) == 48
    assert len(active_frame) == 48
    assert all(rgb == (0, 0, 0) for rgb in off_frame)
    assert any(rgb != (0, 0, 0) for rgb in active_frame)


def test_display_configurator_calibration_step_cycle_uses_strip_zone_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=48))
    dialog._dialog._refresh()

    assert "1/48" in dialog._dialog.current_zone_label._text


def test_display_configurator_can_set_manual_device_zone_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog.device_zone_count_slider.setValue(12)
    updated = dialog.updated_config()
    assert updated.device_zone_count == 12


def test_display_configurator_prefills_device_zone_count_from_runtime_metadata(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=0)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg, runtime_status={"device_zone_count": 48})
    updated = dialog.updated_config()
    assert updated.device_zone_count == 48


def test_display_configurator_updates_live_numeric_labels(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    dialog._dialog.zone_count_slider.setValue(14)
    dialog._dialog.zone_offset_slider.setValue(-3)

    assert dialog._dialog.zone_count_value._text == "14"
    assert dialog._dialog.zone_offset_value._text == "-3 (raw -3)"
    assert "Screen sampling zones" in dialog._dialog.zone_count_explanation._text


def test_display_configurator_uses_compact_default_window_size(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    assert dialog._dialog._resize == (700, 440)

def test_display_configurator_uses_corner_anchor_model(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=8, calibration_model="corner_anchored")
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog._test_step = 1
    dialog._dialog._assign_anchor("top_left")
    dialog._dialog._test_step = 3
    dialog._dialog._assign_anchor("top_right")
    dialog._dialog._test_step = 5
    dialog._dialog._assign_anchor("bottom_right")
    dialog._dialog._test_step = 7
    dialog._dialog._assign_anchor("bottom_left")

    updated = dialog.updated_config()
    assert updated.corner_anchor_top_left >= 0
    assert updated.corner_anchor_top_right >= 0
    assert updated.calibration.calibration_model == "corner_anchored"
    assert updated.calibration.corner_anchor_top_left == updated.corner_anchor_top_left


def test_display_configurator_offset_change_updates_current_physical_zone(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=48, zone_offset=-5)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog._test_step = 11
    dialog._dialog._refresh()
    before = dialog._dialog.current_zone_label._text

    dialog._dialog.zone_offset_slider.setValue(17)
    after = dialog._dialog.current_zone_label._text

    assert before != after


def test_display_configurator_blocks_next_until_calibration_phases_pass(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    assert dialog._dialog.next_button._enabled is False

    dialog._dialog.device_zone_count_slider.setValue(8)
    for step in dialog._dialog._state.calibration_steps():
        dialog._dialog._state.mark_calibration_step(step, passed=True)
    dialog._dialog._refresh()

    assert dialog._dialog.next_button._enabled is True


def test_display_configurator_preserves_passed_phase_when_navigating_back(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    dialog._dialog.calibration_mark_pass_button.clicked.emit()
    assert "passed" in dialog._dialog.calibration_phase_status_label._text

    dialog._dialog.calibration_phase_next_button.clicked.emit()
    dialog._dialog.calibration_phase_prev_button.clicked.emit()
    assert "passed" in dialog._dialog.calibration_phase_status_label._text


def test_display_configurator_persists_and_restores_in_progress_draft(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog._flow.index = 1
    dialog._dialog._test_step = 5
    dialog._dialog.zone_offset_slider.setValue(4)
    draft_cfg = dialog.in_progress_config()
    assert draft_cfg.wizard_in_progress_state

    resumed = DisplayConfiguratorDialog(parent=None, cfg=draft_cfg)
    assert resumed._dialog._flow.index == 1
    assert resumed._dialog._test_step == 5
    assert resumed._dialog.zone_offset_slider.value() == 4
    assert resumed._dialog._state.current_phase


def test_display_configurator_recovery_controls_restore_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    dialog._dialog._calibration_phase_index = 1  # direction-verification
    dialog._dialog.zone_offset_slider.setValue(3)
    dialog._dialog.reverse_checkbox.setChecked(True)
    dialog._dialog.confirm_direction_button.clicked.emit()

    dialog._dialog.zone_offset_slider.setValue(-2)
    dialog._dialog.reverse_checkbox.setChecked(False)
    dialog._dialog.rollback_direction_button.clicked.emit()

    assert dialog._dialog.zone_offset_slider.value() == 3
    assert dialog._dialog.reverse_checkbox.isChecked() is True


def test_display_configurator_retry_and_reset_do_not_clear_other_completed_phases(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    dialog._dialog._state.mark_calibration_step("start-point-detection", passed=True, notes="ok")
    dialog._dialog._state.mark_calibration_step("direction-verification", passed=True, notes="ok")
    dialog._dialog._calibration_phase_index = 2  # corner-assignment

    dialog._dialog.calibration_phase_rerun_button.clicked.emit()
    assert dialog._dialog._state.calibration_step_state("start-point-detection").passed is True
    assert dialog._dialog._state.calibration_step_state("direction-verification").passed is True

    dialog._dialog.calibration_phase_reset_button.clicked.emit()
    assert dialog._dialog._state.calibration_step_state("start-point-detection").passed is True
    assert dialog._dialog._state.calibration_step_state("direction-verification").passed is True


def test_display_configurator_undo_last_calibration_action(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    dialog._dialog._calibration_phase_index = 1
    dialog._dialog.zone_offset_slider.setValue(3)
    before = dialog._dialog.zone_offset_slider.value()
    dialog._dialog.calibration_next_button.clicked.emit()
    dialog._dialog.zone_offset_slider.setValue(-2)

    dialog._dialog.calibration_undo_button.clicked.emit()
    assert dialog._dialog.zone_offset_slider.value() == before


def test_display_configurator_reset_current_phase_restores_boundary_snapshot(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    dialog._dialog._calibration_phase_index = 1
    dialog._dialog._capture_phase_boundary_snapshot()
    expected_reverse = dialog._dialog.reverse_checkbox.isChecked()
    dialog._dialog.zone_offset_slider.setValue(6)
    dialog._dialog.reverse_checkbox.setChecked(True)

    dialog._dialog.calibration_phase_boundary_reset_button.clicked.emit()
    assert dialog._dialog.zone_offset_slider.value() == 0
    assert dialog._dialog.reverse_checkbox.isChecked() is expected_reverse


def test_display_configurator_recovers_local_session_on_reopen(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    dialog._dialog._flow.index = 2
    dialog._dialog._test_step = 4
    dialog._dialog.zone_offset_slider.setValue(5)
    dialog._dialog._save_wizard_session()

    resumed = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[]))
    assert resumed._dialog._flow.index == 2
    assert resumed._dialog._test_step == 4
    assert resumed._dialog.zone_offset_slider.value() == -3
    assert "Recovered unfinished calibration session" in resumed._dialog.zone_change_notice._text


def test_display_configurator_zone_count_change_remaps_anchors_and_shows_notice(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=8, calibration_model="corner_anchored")
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog._state.corner_anchor_top_left = 4
    dialog._dialog.device_zone_count_slider.setValue(16)

    assert dialog._dialog._state.corner_anchor_top_left == 8
    assert "remapped offset and corner anchors" in dialog._dialog.zone_change_notice._text


def test_display_configurator_keeps_next_disabled_when_validation_fails(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    for step in dialog._dialog._state.calibration_steps():
        dialog._dialog._state.mark_calibration_step(step, passed=True)

    dialog._dialog._state.corner_anchor_top_left = 1
    dialog._dialog._state.corner_anchor_top_right = 1
    dialog._dialog._state.corner_anchor_bottom_right = 1
    dialog._dialog._state.corner_anchor_bottom_left = 1
    dialog._dialog._refresh()

    assert dialog._dialog.next_button._enabled is False
