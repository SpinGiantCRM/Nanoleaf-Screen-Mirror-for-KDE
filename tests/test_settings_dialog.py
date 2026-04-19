from __future__ import annotations

import types
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


def _qt_stub() -> dict[str, object]:
    class _DummySignal:
        def __init__(self):
            self._callback = None

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
            self.valueChanged = _DummySignal()

        def setRange(self, _min, _max):
            pass

        def setValue(self, value):
            self._value = value
            if self.valueChanged._callback is not None:
                self.valueChanged._callback()

        def value(self):
            return self._value

        def setEnabled(self, _enabled):
            pass

        def setToolTip(self, _text):
            pass

    class _Check:
        def __init__(self, _label):
            self._value = False
            self.stateChanged = _DummySignal()

        def setChecked(self, value):
            self._value = bool(value)
            if self.stateChanged._callback is not None:
                self.stateChanged._callback()

        def isChecked(self):
            return self._value

        def setToolTip(self, _text):
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
            if self.currentIndexChanged._callback is not None:
                self.currentIndexChanged._callback()

        def currentText(self):
            return self._items[self._index]

        def setToolTip(self, _text):
            pass

    class _Grid:
        def addWidget(self, *_args):
            pass

        def addLayout(self, *_args):
            pass

    class _Label:
        def __init__(self, text):
            self._text = text

        def setText(self, text):
            self._text = text

        def setToolTip(self, _text):
            pass

        def setVisible(self, _visible):
            pass

    class _Button:
        def __init__(self, _text):
            self.clicked = _DummySignal()

        def setToolTip(self, _text):
            pass

    class _Buttons:
        class StandardButton:
            Save = 1
            Cancel = 2

        def __init__(self, _buttons):
            self.accepted = _DummySignal()
            self.rejected = _DummySignal()

    return {
        "QDialog": _QDialog,
        "QDialogButtonBox": _Buttons,
        "QGridLayout": _Grid,
        "QCheckBox": _Check,
        "QComboBox": _Combo,
        "QLabel": _Label,
        "QSlider": _Slider,
        "QPushButton": _Button,
        "Qt": types.SimpleNamespace(Orientation=types.SimpleNamespace(Horizontal=1)),
    }


def test_qt_lazy_exports_qcombobox() -> None:
    qt_lazy = Path("src/nanoleaf_sync/ui/qt_lazy.py").read_text(encoding="utf-8")
    assert "QComboBox" in qt_lazy


def test_settings_dialog_constructs_and_opens_with_qt_stubs(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)

    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        use_mock_capture=False,
        prefer_backend="kwin-dbus",
    )
    dialog = SettingsDialog(parent=None, cfg=cfg)
    assert dialog.exec() == 1
    updated = dialog.updated_config()
    assert updated.prefer_backend == "kwin-dbus"
    assert updated.hdr_transfer in {"srgb", "pq"}
    assert updated.hdr_primaries in {"bt709", "bt2020"}
    assert updated.device_zone_count == 0
    assert updated.output_channel_order == "grb"
    assert updated.color_mode == "default"
    assert updated.start_on_launch is False
    assert updated.hdr_enabled is False

    portal_idx = dialog._dialog.capture_backend_combo.findText("xdg-portal")
    dialog._dialog.capture_backend_combo.setCurrentIndex(portal_idx)
    updated_portal = dialog.updated_config()
    assert updated_portal.prefer_backend == "xdg-portal"


def test_settings_dialog_zone_count_updates_zones_without_forcing_manual_device_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)

    cfg = AppConfig(zones=[], device_zone_count=0)
    dialog = SettingsDialog(parent=None, cfg=cfg)

    dialog._dialog.zone_count_slider.setValue(6)
    updated = dialog.updated_config()

    assert len(updated.zones) == 6
    assert updated.device_zone_count == 0


def test_settings_dialog_updates_zone_sampling_stride(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)

    cfg = AppConfig(zones=[], zone_sampling_stride=1)
    dialog = SettingsDialog(parent=None, cfg=cfg)
    dialog._dialog.zone_sampling_stride_slider.setValue(3)

    updated = dialog.updated_config()
    assert updated.zone_sampling_stride == 3


def test_mapping_preview_uses_explicit_auto_flag() -> None:
    from nanoleaf_sync.ui.settings_dialog import _mapping_preview_text

    auto_text = _mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
        auto_mapping=True,
    )
    manual_text = _mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
        auto_mapping=False,
    )

    assert "Mapping mode: auto" in auto_text
    assert "Mapping mode: manual" in manual_text
