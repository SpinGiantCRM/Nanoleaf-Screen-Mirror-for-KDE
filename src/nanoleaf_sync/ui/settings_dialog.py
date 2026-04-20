from __future__ import annotations

from dataclasses import replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.calibration_preview import calibration_test_frame, corner_anchor_steps, single_zone_step
from nanoleaf_sync.ui.zone_calibration import (
    mapping_preview_text as _mapping_preview_text,
    mapping_preview_visual,
)
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

FPS_MIN = 1
FPS_MAX = 120
HDR_MAX_NITS_MIN = 80
HDR_MAX_NITS_MAX = 10000
ZONE_STRIDE_MIN = 1
ZONE_STRIDE_MAX = 8
class SettingsDialog:
    def __init__(self, parent, cfg: AppConfig, *, calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QDialogButtonBox = qt["QDialogButtonBox"]
        QGridLayout = qt["QGridLayout"]
        QCheckBox = qt["QCheckBox"]
        QComboBox = qt["QComboBox"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("nanoleaf-kde-sync Settings")
                self._open_display_configurator = False
                self._calibration_sender = calibration_sender

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.brightness_slider.setRange(0, 100)
                self.brightness_slider.setValue(int(round(cfg.brightness * 100)))

                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.smoothing_slider.setRange(0, 100)
                self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))
                self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.smoothing_speed_slider.setRange(0, 400)
                self.smoothing_speed_slider.setValue(int(round(getattr(cfg, "smoothing_speed", 0.75) * 100)))

                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.fps_slider.setRange(FPS_MIN, FPS_MAX)
                self.fps_slider.setValue(int(cfg.fps))

                self.display_mode_combo = QComboBox()
                self.display_mode_combo.addItems(["sdr", "hdr"])
                self.display_mode_combo.setCurrentIndex(1 if bool(getattr(cfg, "hdr_enabled", False)) else 0)

                self.color_mode_combo = QComboBox()
                self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"])
                color_mode_idx = self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))
                self.color_mode_combo.setCurrentIndex(max(0, color_mode_idx))

                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens")
                self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))
                self.start_on_launch_checkbox.setToolTip("Automatically start mirroring after the tray icon appears.")

                zone_count = len(cfg.zones) if cfg.zones else (int(getattr(cfg, "device_zone_count", 0)) or 8)
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(int(zone_count))
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["edge-weighted", "horizontal"])
                zone_preset_idx = self.zone_preset_combo.findText(str(getattr(cfg, "zone_preset", "edge-weighted")))
                self.zone_preset_combo.setCurrentIndex(max(0, zone_preset_idx))

                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(int(getattr(cfg, "zone_offset", 0)))

                self.reverse_checkbox = QCheckBox("Reverse strip orientation")
                self.reverse_checkbox.setChecked(bool(getattr(cfg, "reverse_zones", False)))
                self.reverse_checkbox.setToolTip("Flip strip direction when colors appear mirrored left-to-right.")

                device_zone_count = int(getattr(cfg, "device_zone_count", 0)) or int(zone_count)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(device_zone_count)
                self.device_zone_count_auto_checkbox = QCheckBox("Auto device zone count (match detected strip length)")
                self.device_zone_count_auto_checkbox.setChecked(int(getattr(cfg, "device_zone_count", 0)) == 0)
                self.manual_map_checkbox = QCheckBox("Advanced: manual zone map")
                self.manual_map_checkbox.setChecked(bool(getattr(cfg, "explicit_zone_map", [])))
                self.manual_map_checkbox.setToolTip("Enable only for non-standard strip layouts.")
                self.manual_map_device_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.manual_map_device_slider.setRange(0, max(0, device_zone_count - 1))
                self.manual_map_device_slider.setValue(0)
                self.manual_map_source_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.manual_map_source_slider.setRange(0, max(0, zone_count - 1))
                explicit_map = [int(i) for i in (getattr(cfg, "explicit_zone_map", []) or [])]
                first_manual = explicit_map[0] if explicit_map else 0
                self.manual_map_source_slider.setValue(max(0, first_manual))
                self.manual_map_apply_button = QPushButton("Apply mapping for selected strip zone")
                self.test_step_button = QPushButton("Next test zone")
                self.test_prev_button = QPushButton("Previous test zone")
                self.test_send_button = QPushButton("Send test pattern")
                self.test_mode_combo = QComboBox()
                self.test_mode_combo.addItems(["single active zone", "corner anchors"])

                self.output_channel_order_combo = QComboBox()
                self.output_channel_order_combo.addItems(["grb", "rgb", "rbg", "gbr", "brg", "bgr"])
                output_channel_order = str(getattr(cfg, "output_channel_order", "grb"))
                output_channel_order_idx = self.output_channel_order_combo.findText(output_channel_order)
                self.output_channel_order_combo.setCurrentIndex(max(0, output_channel_order_idx))

                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)")
                self.mock_capture_checkbox.setChecked(bool(getattr(cfg, "use_mock_capture", True)))

                self.capture_backend_combo = QComboBox()
                self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"])
                backend_idx = self.capture_backend_combo.findText(str(getattr(cfg, "prefer_backend", "kwin-dbus")))
                self.capture_backend_combo.setCurrentIndex(max(0, backend_idx))

                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq"])
                transfer_idx = self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))
                self.hdr_transfer_combo.setCurrentIndex(max(0, transfer_idx))

                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                primaries_idx = self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))
                self.hdr_primaries_combo.setCurrentIndex(max(0, primaries_idx))

                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(HDR_MAX_NITS_MIN, HDR_MAX_NITS_MAX)
                self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))
                self.zone_sampling_stride_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_sampling_stride_slider.setRange(ZONE_STRIDE_MIN, ZONE_STRIDE_MAX)
                self.zone_sampling_stride_slider.setValue(int(getattr(cfg, "zone_sampling_stride", 1)))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.led_gamma_slider.setRange(100, 400)
                self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 1.0) * 100)))

                self.display_configurator_button = QPushButton("Re-run Display Setup")
                self.display_configurator_button.clicked.connect(self._open_configurator)

                self._manual_map = explicit_map[:]
                self._test_step = 0
                self.preview_label = QLabel("")
                self.preview_visual_label = QLabel("")
                self.test_label = QLabel("")
                self.brightness_value = QLabel("")
                self.smoothing_value = QLabel("")
                self.fps_value = QLabel("")
                self.zone_count_value = QLabel("")
                self.zone_offset_value = QLabel("")
                self.device_zone_count_value = QLabel("")
                self.hdr_max_nits_value = QLabel("")
                self.zone_sampling_stride_value = QLabel("")
                self.smoothing_speed_value = QLabel("")
                self.led_gamma_value = QLabel("")

                self._refresh_numeric_labels()
                self._refresh_preview_label()
                self.brightness_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.smoothing_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.smoothing_speed_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.fps_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.zone_preset_combo.currentIndexChanged.connect(self._on_calibration_control_changed)
                self.zone_offset_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.device_zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.device_zone_count_auto_checkbox.stateChanged.connect(self._on_calibration_control_changed)
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_sampling_stride_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.led_gamma_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.reverse_checkbox.stateChanged.connect(self._refresh_preview_label)
                self.manual_map_checkbox.stateChanged.connect(self._refresh_preview_label)
                self.manual_map_device_slider.valueChanged.connect(self._sync_manual_source_slider)
                self.manual_map_source_slider.valueChanged.connect(self._refresh_preview_label)
                self.manual_map_apply_button.clicked.connect(self._apply_manual_mapping)
                self.test_step_button.clicked.connect(self._step_test_zone)
                self.test_prev_button.clicked.connect(self._prev_test_zone)
                self.test_send_button.clicked.connect(self._send_test_pattern)
                self.test_mode_combo.currentIndexChanged.connect(self._refresh_preview_label)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QGridLayout()

                def _add_labeled(row: int, text: str, control, value_label=None, *, tooltip: str = "") -> None:
                    label = QLabel(text)
                    if tooltip:
                        label.setToolTip(tooltip)
                        control.setToolTip(tooltip)
                    layout.addWidget(label, row, 0)
                    layout.addWidget(control, row, 1)
                    if value_label is not None:
                        layout.addWidget(value_label, row, 2)

                layout.addWidget(QLabel("Display / Image Behaviour"), 0, 0, 1, 2)
                _add_labeled(1, "SDR/HDR mode", self.display_mode_combo, tooltip="SDR is safest and simplest. HDR is for true HDR display/content paths.")
                _add_labeled(2, "Colour behaviour preset", self.color_mode_combo, tooltip="Default (recommended) tuned look; Balanced safer; Dynamic more reactive; Hyper most intense.")
                _add_labeled(3, "HDR transfer", self.hdr_transfer_combo, tooltip="sRGB is safer for SDR-like workflows. PQ is the HDR transfer curve for HDR content.")
                _add_labeled(4, "HDR primaries", self.hdr_primaries_combo, tooltip="BT.709 is standard and safer. BT.2020 keeps wider HDR colour gamut when supported.")
                _add_labeled(5, "HDR max brightness", self.hdr_max_nits_slider, self.hdr_max_nits_value, tooltip="Tone-mapping reference in nits. Too high/low can look dull, clipped, or wrong.")
                layout.addWidget(self.display_configurator_button, 6, 0, 1, 2)

                layout.addWidget(QLabel("Runtime / Performance"), 7, 0, 1, 2)
                _add_labeled(8, "Brightness", self.brightness_slider, self.brightness_value, tooltip="Controls LED intensity.")
                _add_labeled(9, "Smoothing (min cutoff)", self.smoothing_slider, self.smoothing_value, tooltip="Higher smoothing reduces flicker but adds delay.")
                _add_labeled(10, "Smoothing speed coefficient", self.smoothing_speed_slider, self.smoothing_speed_value, tooltip="How fast smoothing loosens when colours change quickly.")
                _add_labeled(11, "Capture FPS", self.fps_slider, self.fps_value, tooltip="Higher values can reduce latency but use more resources.")
                _add_labeled(12, "Zone sampling stride", self.zone_sampling_stride_slider, self.zone_sampling_stride_value, tooltip="Higher values sample fewer pixels per zone and reduce CPU at the cost of precision.")

                layout.addWidget(QLabel("Zone Calibration"), 13, 0, 1, 3)
                layout.addWidget(
                    QLabel(
                        "Calibrate strip order from left/right/top/bottom screen colours.\n"
                        "Simple mode: choose count + preset, then adjust reverse/offset until the test order matches."
                    ),
                    14,
                    0,
                    1,
                    3,
                )
                _add_labeled(15, "Zone count", self.zone_count_slider, self.zone_count_value)
                _add_labeled(16, "Zone layout preset", self.zone_preset_combo)
                _add_labeled(17, "Start offset (rotation)", self.zone_offset_slider, self.zone_offset_value)
                layout.addWidget(self.reverse_checkbox, 18, 0, 1, 2)
                _add_labeled(19, "Device zone count", self.device_zone_count_slider, self.device_zone_count_value)
                layout.addWidget(self.device_zone_count_auto_checkbox, 20, 0, 1, 2)
                layout.addWidget(self.test_step_button, 21, 0, 1, 2)
                layout.addWidget(self.test_prev_button, 21, 2, 1, 1)
                _add_labeled(22, "Test mode", self.test_mode_combo)
                layout.addWidget(self.test_send_button, 23, 0, 1, 2)
                layout.addWidget(self.test_label, 24, 0, 1, 3)
                layout.addWidget(self.manual_map_checkbox, 25, 0, 1, 2)
                _add_labeled(26, "Manual map: strip zone", self.manual_map_device_slider)
                _add_labeled(27, "Manual map: screen zone", self.manual_map_source_slider)
                layout.addWidget(self.manual_map_apply_button, 28, 0, 1, 2)
                _add_labeled(29, "Output channel order", self.output_channel_order_combo)

                layout.addWidget(self.start_on_launch_checkbox, 30, 0, 1, 2)
                layout.addWidget(self.mock_capture_checkbox, 31, 0, 1, 2)
                _add_labeled(32, "Capture backend", self.capture_backend_combo)
                _add_labeled(33, "LED gamma", self.led_gamma_slider, self.led_gamma_value)
                layout.addWidget(self.preview_label, 34, 0, 1, 3)
                layout.addWidget(self.preview_visual_label, 35, 0, 1, 3)
                layout.addWidget(buttons, 36, 0, 1, 3)
                self.setLayout(layout)

            def _open_configurator(self) -> None:
                self._open_display_configurator = True
                self.accept()

            def wants_display_configurator(self) -> bool:
                return bool(self._open_display_configurator)

            def _on_calibration_control_changed(self) -> None:
                self._refresh_numeric_labels()
                self.manual_map_device_slider.setRange(0, max(0, self._effective_device_zone_count() - 1))
                self.manual_map_source_slider.setRange(0, max(0, int(self.zone_count_slider.value()) - 1))
                self._refresh_preview_label()

            def _refresh_numeric_labels(self) -> None:
                self.brightness_value.setText(f"{self.brightness_slider.value()}%")
                self.smoothing_value.setText(f"{self.smoothing_slider.value()}%")
                self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}")
                self.fps_value.setText(f"{self.fps_slider.value()} fps")
                self.zone_sampling_stride_value.setText(str(self.zone_sampling_stride_slider.value()))
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                if self.device_zone_count_auto_checkbox.isChecked():
                    self.device_zone_count_value.setText("auto")
                    self.device_zone_count_slider.setEnabled(False)
                else:
                    self.device_zone_count_value.setText(str(self.device_zone_count_slider.value()))
                    self.device_zone_count_slider.setEnabled(True)
                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
                self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}")

            def _refresh_preview_label(self) -> None:
                explicit_map = self._manual_map if self.manual_map_checkbox.isChecked() else []
                self.preview_label.setText(
                    _mapping_preview_text(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=self._effective_device_zone_count(),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                        explicit_zone_map=explicit_map,
                    )
                )
                self.preview_visual_label.setText(
                    mapping_preview_visual(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=self._effective_device_zone_count(),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                        explicit_zone_map=explicit_map,
                    )
                )
                self.manual_map_device_slider.setEnabled(self.manual_map_checkbox.isChecked())
                self.manual_map_source_slider.setEnabled(self.manual_map_checkbox.isChecked())
                self.manual_map_apply_button.setEnabled(self.manual_map_checkbox.isChecked())
                step = self._current_calibration_step()
                self.test_label.setText(step.label)

            def _effective_device_zone_count(self) -> int:
                return (
                    int(self.zone_count_slider.value())
                    if self.device_zone_count_auto_checkbox.isChecked()
                    else int(self.device_zone_count_slider.value())
                )

            def _sync_manual_source_slider(self) -> None:
                idx = int(self.manual_map_device_slider.value())
                if idx < len(self._manual_map):
                    self.manual_map_source_slider.setValue(int(self._manual_map[idx]))
                else:
                    self.manual_map_source_slider.setValue(0)

            def _apply_manual_mapping(self) -> None:
                idx = int(self.manual_map_device_slider.value())
                val = int(self.manual_map_source_slider.value())
                if idx >= len(self._manual_map):
                    self._manual_map.extend([0] * (idx + 1 - len(self._manual_map)))
                self._manual_map[idx] = val
                self._refresh_preview_label()

            def _step_test_zone(self) -> None:
                self._test_step = (self._test_step + 1) % max(1, self._effective_device_zone_count())
                self._refresh_preview_label()
                self._send_test_pattern()

            def _prev_test_zone(self) -> None:
                self._test_step = (self._test_step - 1) % max(1, self._effective_device_zone_count())
                self._refresh_preview_label()
                self._send_test_pattern()

            def _current_calibration_step(self):
                if str(self.test_mode_combo.currentText()) == "corner anchors":
                    anchors = corner_anchor_steps(device_zone_count=self._effective_device_zone_count())
                    return anchors[self._test_step % len(anchors)]
                explicit_map = self._manual_map if self.manual_map_checkbox.isChecked() else []
                return single_zone_step(
                    step=self._test_step,
                    zone_count=int(self.zone_count_slider.value()),
                    device_zone_count=self._effective_device_zone_count(),
                    zone_offset=int(self.zone_offset_slider.value()),
                    reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    explicit_zone_map=explicit_map,
                )

            def _send_test_pattern(self) -> None:
                if self._calibration_sender is None:
                    return
                step = self._current_calibration_step()
                colors = calibration_test_frame(
                    device_zone_count=self._effective_device_zone_count(),
                    active_indices=[step.device_zone_index],
                )
                self._calibration_sender(colors)

            def updated_config(self) -> AppConfig:
                zone_count = int(self.zone_count_slider.value())
                zone_preset = str(self.zone_preset_combo.currentText())
                new_zones = make_edge_weighted_zones(zone_count) if zone_preset == "edge-weighted" else make_horizontal_zones(zone_count)
                return replace(
                    cfg,
                    fps=int(self.fps_slider.value()),
                    zone_sampling_stride=int(self.zone_sampling_stride_slider.value()),
                    brightness=self.brightness_slider.value() / 100.0,
                    smoothing=self.smoothing_slider.value() / 100.0,
                    smoothing_speed=self.smoothing_speed_slider.value() / 100.0,
                    led_gamma=self.led_gamma_slider.value() / 100.0,
                    zones=new_zones,
                    zone_preset=zone_preset,
                    color_mode=str(self.color_mode_combo.currentText()),
                    hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()),
                    device_zone_count=0 if self.device_zone_count_auto_checkbox.isChecked() else int(self.device_zone_count_slider.value()),
                    output_channel_order=str(self.output_channel_order_combo.currentText()),
                    zone_offset=int(self.zone_offset_slider.value()),
                    reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    explicit_zone_map=(self._manual_map[: self._effective_device_zone_count()] if self.manual_map_checkbox.isChecked() else []),
                    use_mock_capture=bool(self.mock_capture_checkbox.isChecked()),
                    prefer_backend=str(self.capture_backend_combo.currentText()),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()

    def wants_display_configurator(self) -> bool:
        return bool(self._dialog.wants_display_configurator())
