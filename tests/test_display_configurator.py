from __future__ import annotations

import types

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog


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

        def accept(self):
            return None

        def reject(self):
            return None

        def exec(self):
            return 1

    class _Slider:
        def __init__(self, _orientation):
            self._value = 0
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
            pass

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

        def setVisible(self, _visible):
            pass

    class _Button:
        def __init__(self, _text):
            self.clicked = _DummySignal()

    class _Layout:
        def addWidget(self, *_args):
            pass

        def addLayout(self, *_args):
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


def test_display_configurator_marks_wizard_complete_and_saves_calibration(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(wizard_completed=False, zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog.zone_count_slider.setValue(6)
    dialog._dialog.zone_offset_slider.setValue(2)
    dialog._dialog.reverse_checkbox.setChecked(True)

    updated = dialog.updated_config()
    assert updated.wizard_completed is True
    assert len(updated.zones) == 6
    assert updated.zone_offset == 2
    assert updated.reverse_zones is True


def test_display_configurator_can_set_manual_device_zone_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _qt_stub)
    cfg = AppConfig(zones=[])
    dialog = DisplayConfiguratorDialog(parent=None, cfg=cfg)
    dialog._dialog.device_zone_count_auto_checkbox.setChecked(False)
    dialog._dialog.device_zone_count_slider.setValue(12)
    updated = dialog.updated_config()
    assert updated.device_zone_count == 12
