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
            self._tooltip = ""
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
            self._tooltip = _text

    class _Check:
        def __init__(self, _label):
            self._value = False
            self._tooltip = ""
            self.stateChanged = _DummySignal()

        def setChecked(self, value):
            self._value = bool(value)
            if self.stateChanged._callback is not None:
                self.stateChanged._callback()

        def isChecked(self):
            return self._value

        def setToolTip(self, _text):
            self._tooltip = _text

    class _Combo:
        def __init__(self):
            self._items = []
            self._index = 0
            self._tooltip = ""
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
            self._tooltip = _text

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
        def __init__(self, text):
            self._text = text
            self.clicked = _DummySignal()

        def setToolTip(self, _text):
            pass

        def setEnabled(self, _enabled):
            pass

        def setText(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Buttons:
        class StandardButton:
            Save = 1
            Cancel = 2

        def __init__(self, _buttons):
            self.accepted = _DummySignal()
            self.rejected = _DummySignal()

    class _Timer:
        def __init__(self, *_args, **_kwargs):
            self.timeout = _DummySignal()
            self._active = False
            self._interval = None

        def start(self, ms):
            self._active = True
            self._interval = ms

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

        def setInterval(self, ms):
            self._interval = ms

    return {
        "QDialog": _QDialog,
        "QDialogButtonBox": _Buttons,
        "QGridLayout": _Grid,
        "QCheckBox": _Check,
        "QComboBox": _Combo,
        "QLabel": _Label,
        "QSlider": _Slider,
        "QPushButton": _Button,
        "QTimer": _Timer,
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
    assert updated.device_zone_count == 1
    assert updated.output_channel_order == "grb"
    assert updated.color_mode == "default"
    assert updated.start_on_launch is False
    assert updated.hdr_enabled is False
    assert updated.auto_probe_policy in {"on-change", "first-run", "each-boot"}
    assert updated.device_vid == 0x37FA
    assert updated.device_pid in {0x8201, 0x8202}
    assert updated.sdr_boost_nits >= 80.0

    portal_idx = dialog._dialog.capture_backend_combo.findText("xdg-portal")
    dialog._dialog.capture_backend_combo.setCurrentIndex(portal_idx)
    each_boot_idx = dialog._dialog.auto_probe_policy_combo.findText("each-boot")
    dialog._dialog.auto_probe_policy_combo.setCurrentIndex(each_boot_idx)
    updated_portal = dialog.updated_config()
    assert updated_portal.prefer_backend == "xdg-portal"
    assert updated_portal.auto_probe_policy == "each-boot"


def test_settings_dialog_supports_device_model_selection(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(device_vid=0x37FA, device_pid=0x8202)
    dialog = SettingsDialog(parent=None, cfg=cfg)

    k1_idx = dialog._dialog.device_model_combo.findText("NL82K1 Dock (PID 0x8201)")
    dialog._dialog.device_model_combo.setCurrentIndex(k1_idx)
    updated = dialog.updated_config()
    assert updated.device_vid == 0x37FA
    assert updated.device_pid == 0x8201


def test_settings_dialog_zone_count_updates_zones_without_changing_configured_device_count(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)

    cfg = AppConfig(zones=[], device_zone_count=0)
    dialog = SettingsDialog(parent=None, cfg=cfg)

    dialog._dialog.zone_count_slider.setValue(6)
    updated = dialog.updated_config()

    assert len(updated.zones) == 6
    assert updated.device_zone_count == 8


def test_settings_dialog_saves_zone_preset_reverse_and_offset(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=0, zone_preset="edge-weighted")
    dialog = SettingsDialog(parent=None, cfg=cfg)

    horizontal_idx = dialog._dialog.zone_preset_combo.findText("horizontal")
    dialog._dialog.zone_preset_combo.setCurrentIndex(horizontal_idx)
    dialog._dialog.reverse_checkbox.setChecked(True)
    dialog._dialog.zone_offset_slider.setValue(3)
    dialog._dialog.zone_count_slider.setValue(5)

    updated = dialog.updated_config()
    assert updated.zone_preset == "horizontal"
    assert updated.reverse_zones is True
    assert updated.zone_offset == 3
    assert len(updated.zones) == 5


def test_settings_dialog_updates_sampling_quality(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)

    cfg = AppConfig(zones=[], sampling_quality="balanced")
    dialog = SettingsDialog(parent=None, cfg=cfg)
    high_idx = dialog._dialog.sampling_quality_combo.findText("High")
    dialog._dialog.sampling_quality_combo.setCurrentIndex(high_idx)

    updated = dialog.updated_config()
    assert updated.sampling_quality == "high"


def test_settings_dialog_uses_measured_latency_when_runtime_samples_available(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(fps=60, prefer_backend="kwin-dbus")
    dialog = SettingsDialog(
        parent=None,
        cfg=cfg,
        runtime_status={
            "running": True,
            "effective_capture_backend": "kwin-dbus",
            "latency_measurement": {
                "sample_count": 12,
                "capture_interval_median_ms": 16.7,
                "capture_interval_p95_ms": 19.1,
                "pipeline_median_ms": 28.3,
                "pipeline_p95_ms": 35.0,
                "pipeline_jitter_ms": 9.4,
            },
        },
    )

    dialog._dialog._run_latency_probe_manual()
    assert dialog._dialog._latest_latency is not None
    assert dialog._dialog._latest_latency.measurement_kind == "measured"
    assert "samples=12" in dialog._dialog._latest_latency.details
    assert dialog._dialog.run_latency_button.text() == "Measure frame interval"


def test_settings_dialog_falls_back_to_estimate_when_no_runtime_samples(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(fps=40, prefer_backend="kwin-dbus")
    dialog = SettingsDialog(
        parent=None,
        cfg=cfg,
        runtime_status={"running": False, "effective_capture_backend": "not-started"},
    )

    dialog._dialog._run_latency_probe_manual()
    assert dialog._dialog._latest_latency is not None
    assert dialog._dialog._latest_latency.measurement_kind == "estimated"
    assert dialog._dialog.run_latency_button.text() == "Estimate frame interval"


def test_mapping_preview_uses_explicit_auto_flag() -> None:
    from nanoleaf_sync.ui.settings_dialog import _mapping_preview_text

    auto_text = _mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
    )
    manual_text = _mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
        explicit_zone_map=[0, 1, 2],
    )

    assert "Calibration model: offset + direction" in auto_text
    assert "Device zone order" in manual_text


def test_settings_dialog_uses_wizard_calibration_model(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0), ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0)])
    dialog = SettingsDialog(parent=None, cfg=cfg)

    updated = dialog.updated_config()
    assert updated.explicit_zone_map == []
    assert updated.corner_offsets_enabled is False
    assert updated.corner_zone_offsets == [0, 0, 0, 0]


def test_settings_dialog_preserves_manual_and_corner_mapping(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        manual_mapping_enabled=True,
        explicit_zone_map=[3, 2, 1, 0],
        corner_offsets_enabled=True,
        corner_zone_offsets=[1, -1, 2, -2],
    )
    dialog = SettingsDialog(parent=None, cfg=cfg)

    updated = dialog.updated_config()
    assert updated.manual_mapping_enabled is True
    assert updated.explicit_zone_map == [3, 2, 1, 0]
    assert updated.corner_offsets_enabled is True
    assert updated.corner_zone_offsets == [1, -1, 2, -2]


def test_settings_dialog_disables_manual_mapping_when_not_enabled(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        manual_mapping_enabled=False,
        explicit_zone_map=[3, 2, 1, 0],
    )
    dialog = SettingsDialog(parent=None, cfg=cfg)

    updated = dialog.updated_config()
    assert updated.manual_mapping_enabled is False
    assert updated.explicit_zone_map == []


def test_settings_dialog_defaults_mock_capture_to_config_default(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    dialog = SettingsDialog(parent=None, cfg=AppConfig(zones=[]))
    assert dialog._dialog.mock_capture_checkbox.isChecked() is False


def test_settings_dialog_does_not_expose_legacy_manual_mapping_controls(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    dialog = SettingsDialog(parent=None, cfg=AppConfig(zones=[]))

    assert not hasattr(dialog._dialog, "manual_map_checkbox")
    assert not hasattr(dialog._dialog, "manual_map_device_slider")
    assert not hasattr(dialog._dialog, "manual_map_source_slider")
    assert not hasattr(dialog._dialog, "corner_offsets_enabled_checkbox")


def test_settings_dialog_can_send_calibration_pattern(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    sent = {"colors": None}

    def _sender(colors):
        sent["colors"] = colors

    dialog = SettingsDialog(parent=None, cfg=AppConfig(zones=[]), calibration_sender=_sender)
    dialog._dialog.test_step_button.clicked._callback()
    assert sent["colors"] is not None
    assert any(rgb != (0, 0, 0) for rgb in sent["colors"])


def test_settings_dialog_interval_slider_updates_running_timer(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    dialog = SettingsDialog(parent=None, cfg=AppConfig(zones=[], device_zone_count=0))
    dialog._dialog.test_auto_checkbox.setChecked(True)
    dialog._dialog.test_step_interval_slider.setValue(750)

    assert dialog._dialog._test_timer._interval == 750


def test_settings_dialog_applies_tooltips_to_key_controls(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    dialog = SettingsDialog(parent=None, cfg=AppConfig(zones=[]))

    assert dialog._dialog.brightness_slider._tooltip
    assert dialog._dialog.smoothing_slider._tooltip
    assert dialog._dialog.smoothing_speed_slider._tooltip
    assert dialog._dialog.fps_slider._tooltip
    assert dialog._dialog.sampling_quality_combo._tooltip
    assert dialog._dialog.led_gamma_slider._tooltip
    assert dialog._dialog.zone_count_slider._tooltip
    assert dialog._dialog.zone_offset_slider._tooltip
    assert dialog._dialog.reverse_checkbox._tooltip
    assert dialog._dialog.display_mode_combo._tooltip
    assert dialog._dialog.color_mode_combo._tooltip
    assert dialog._dialog.hdr_max_nits_slider._tooltip

def test_settings_dialog_saves_corner_anchor_assignments(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], device_zone_count=8)
    dialog = SettingsDialog(parent=None, cfg=cfg)

    dialog._dialog._test_step = 2
    dialog._dialog._assign_anchor("top_left")
    dialog._dialog._test_step = 4
    dialog._dialog._assign_anchor("top_right")

    updated = dialog.updated_config()
    assert updated.corner_anchor_top_left >= 0
    assert updated.corner_anchor_top_right >= 0


def test_settings_dialog_preserves_wizard_resume_draft(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _qt_stub)
    cfg = AppConfig(zones=[], wizard_in_progress_state='{"flow_index": 1, "test_step": 3}')
    dialog = SettingsDialog(parent=None, cfg=cfg)

    updated = dialog.updated_config()
    assert updated.wizard_in_progress_state == cfg.wizard_in_progress_state
