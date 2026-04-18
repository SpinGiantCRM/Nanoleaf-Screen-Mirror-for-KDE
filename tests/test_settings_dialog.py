from __future__ import annotations

import types
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


def test_qt_lazy_exports_qcombobox() -> None:
    qt_lazy = Path("src/nanoleaf_sync/ui/qt_lazy.py").read_text(encoding="utf-8")
    assert "QComboBox" in qt_lazy


def test_settings_dialog_constructs_and_opens_with_qt_stubs(monkeypatch) -> None:
    class _DummySignal:
        def connect(self, callback):
            self._callback = callback

    class _QDialog:
        def __init__(self, parent=None):
            self.parent = parent

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

        def setRange(self, _min, _max):
            pass

        def setValue(self, value):
            self._value = value

        def value(self):
            return self._value

    class _Check:
        def __init__(self, _label):
            self._value = False

        def setChecked(self, value):
            self._value = bool(value)

        def isChecked(self):
            return self._value

    class _Combo:
        def __init__(self):
            self._items = []
            self._index = 0

        def addItems(self, items):
            self._items.extend(items)

        def findText(self, value):
            try:
                return self._items.index(value)
            except ValueError:
                return -1

        def setCurrentIndex(self, idx):
            self._index = idx

        def currentText(self):
            return self._items[self._index]

    class _Grid:
        def addWidget(self, *_args):
            pass

    class _Label:
        def __init__(self, _text):
            pass

    class _Buttons:
        class StandardButton:
            Ok = 1
            Cancel = 2

        def __init__(self, _buttons):
            self.accepted = _DummySignal()
            self.rejected = _DummySignal()

    qt_stub = {
        "QDialog": _QDialog,
        "QDialogButtonBox": _Buttons,
        "QGridLayout": _Grid,
        "QCheckBox": _Check,
        "QComboBox": _Combo,
        "QLabel": _Label,
        "QSlider": _Slider,
        "Qt": types.SimpleNamespace(Orientation=types.SimpleNamespace(Horizontal=1)),
    }
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", lambda: qt_stub)

    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        use_mock_capture=False,
        use_mock_device=True,
        prefer_backend="kwin-dbus",
    )
    dialog = SettingsDialog(parent=None, cfg=cfg)
    assert dialog.exec() == 1
    updated = dialog.updated_config()
    assert updated.prefer_backend == "kwin-dbus"
