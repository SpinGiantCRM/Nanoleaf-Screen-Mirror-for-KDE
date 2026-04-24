from __future__ import annotations

import json
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
            pass

        def setWindowTitle(self, _title):
            pass

        def setLayout(self, _layout):
            pass

        def resize(self, _w, _h):
            pass

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

        def setEnabled(self, enabled):
            self._enabled = bool(enabled)

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
        def __init__(self, text=""):
            self._text = text

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


def test_display_configurator_uses_shared_simple_calibration_widget(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))

    assert dialog._dialog.reverse_checkbox is dialog._dialog.simple_calibration_widget.reverse_orientation_checkbox
    assert dialog._dialog.calibration_next_button is dialog._dialog.simple_calibration_widget.next_zone_button
    assert dialog._dialog.calibration_prev_button is dialog._dialog.simple_calibration_widget.prev_zone_button


def test_display_configurator_marks_wizard_complete_and_persists_corner_calibration(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(wizard_completed=False, zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog.zone_count_slider.setValue(6)
    dialog._dialog.zone_offset_slider.setValue(2)
    dialog._dialog.reverse_checkbox.setChecked(True)

    updated = dialog.updated_config()
    assert updated.wizard_completed is True
    assert updated.calibration.calibration_model == "corner_anchored"
    assert updated.zone_offset == 2
    assert updated.reverse_zones is True


def test_display_configurator_send_pattern_uses_configured_device_zone_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    sent: list[list[tuple[int, int, int]]] = []

    dialog = DisplayConfiguratorDialog(
        parent=None,
        cfg=AppConfig(zones=[]),
        calibration_sender=lambda colors: sent.append(colors),
    )
    dialog._dialog.device_zone_count_slider.setValue(48)
    dialog._dialog.calibration_send_button.clicked.emit()

    assert len(sent) == 2
    assert len(sent[-1]) == 48


def test_display_configurator_restores_in_progress_draft(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    raw = json.dumps(
        {
            "flow_index": 1,
            "test_step": 3,
            "zone_offset": 4,
            "current_phase": "direction-verification",
            "phase_validation_state": {"direction-verification": {"valid": False}},
        }
    )
    cfg = AppConfig(zones=[], wizard_in_progress_state=raw)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)

    assert dialog._dialog._flow.index == 1
    assert dialog._dialog.zone_offset_slider.value() == 4
    stored = json.loads(dialog.in_progress_config().wizard_in_progress_state)
    assert "current_phase" not in stored
    assert "phase_validation_state" not in stored


def test_display_configurator_prefers_detected_zone_count_over_legacy_default_on_first_run(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(
        zones=[],
        wizard_completed=False,
        device_zone_count=8,
    )
    cfg.calibration.device_zone_count = 8
    dialog = DisplayConfiguratorDialog(
        parent=None,
        cfg=cfg,
        runtime_status={"device_zone_count": 48},
    )

    updated = dialog.updated_config()
    assert updated.device_zone_count == 48
    assert updated.calibration.device_zone_count == 48


def test_display_configurator_finishes_using_wizard_in_progress_zone_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(
        zones=[],
        wizard_completed=False,
        device_zone_count=8,
        wizard_in_progress_state=json.dumps({"flow_index": 2, "device_zone_count": 48}),
    )
    cfg.calibration.device_zone_count = 8
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)

    updated = dialog.updated_config()
    assert updated.device_zone_count == 48
    assert updated.calibration.device_zone_count == 48


def test_display_configurator_finish_is_blocked_until_corner_anchors_are_valid(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    dialog = DisplayConfiguratorDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=8))
    dialog._dialog._flow.index = 2
    dialog._dialog._state.corner_anchor_top_left = 0
    dialog._dialog._state.corner_anchor_top_right = 0
    dialog._dialog._state.corner_anchor_bottom_right = 4
    dialog._dialog._state.corner_anchor_bottom_left = 6
    dialog._dialog._refresh()

    assert dialog._dialog.finish_button._enabled is False
    assert "valid corner anchors" in dialog._dialog.finish_policy_note._text.lower()
