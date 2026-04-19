from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices

from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones


def _mapping_preview_text(*, zone_count: int, device_zone_count: int, zone_offset: int, reverse_zones: bool, auto_mapping: bool = True) -> str:
    indices = resolve_device_zone_indices(
        zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse=reverse_zones,
    )
    if not indices:
        return "Calibration preview: no zones configured."
    preview = ", ".join(str(i) for i in indices[:12])
    suffix = "…" if len(indices) > 12 else ""
    mapping_mode = "auto" if auto_mapping else "manual"
    return (
        f"Mapping mode: {mapping_mode} | screen zones: {zone_count} | output zones: {device_zone_count}\n"
        f"Calibration preview (device→screen zones): {preview}{suffix}"
    )


class SettingsDialog:
    """
    Settings dialog (created dynamically with Qt types).

    Keeping this as a plain Python class allows lazy Qt imports.
    """

    def __init__(self, parent, cfg: AppConfig):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QDialogButtonBox = qt["QDialogButtonBox"]
        QGridLayout = qt["QGridLayout"]
        QCheckBox = qt["QCheckBox"]
        QComboBox = qt["QComboBox"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("nanoleaf-kde-sync Settings")

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
                self.fps_slider.setRange(1, 60)
                self.fps_slider.setValue(int(cfg.fps))
                self.color_mode_combo = QComboBox()
                self.color_mode_combo.addItems(["balanced", "dynamic"])
                color_mode_idx = self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "balanced")))
                self.color_mode_combo.setCurrentIndex(max(0, color_mode_idx))
                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens")
                self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))
                self.start_on_launch_checkbox.setToolTip("Automatically start mirroring after the tray icon appears.")

                # Derive zone_count from existing zones; if empty, default to 1.
                zone_count = len(cfg.zones) if cfg.zones else 1
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(int(zone_count))
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["edge-weighted", "horizontal"])
                zone_preset_idx = self.zone_preset_combo.findText(str(getattr(cfg, "zone_preset", "edge-weighted")))
                self.zone_preset_combo.setCurrentIndex(max(0, zone_preset_idx))

                # Calibration controls (mapping sampled zones -> physical strip zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(int(getattr(cfg, "zone_offset", 0)))

                self.reverse_checkbox = QCheckBox("Reverse strip orientation")
                self.reverse_checkbox.setChecked(
                    bool(getattr(cfg, "reverse_zones", False))
                )
                self.reverse_checkbox.setToolTip("Flip strip direction when colors appear mirrored left-to-right.")

                device_zone_count = int(getattr(cfg, "device_zone_count", 0)) or int(
                    zone_count
                )
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(device_zone_count)
                self.device_zone_count_auto_checkbox = QCheckBox("Auto device zone count (match detected strip length)")
                self.device_zone_count_auto_checkbox.setChecked(int(getattr(cfg, "device_zone_count", 0)) == 0)
                self.device_zone_count_auto_checkbox.setToolTip("Use the strip zone count reported by the connected device.")

                self.output_channel_order_combo = QComboBox()
                self.output_channel_order_combo.addItems(["grb", "rgb", "rbg", "gbr", "brg", "bgr"])
                output_channel_order = str(getattr(cfg, "output_channel_order", "grb"))
                output_channel_order_idx = self.output_channel_order_combo.findText(output_channel_order)
                self.output_channel_order_combo.setCurrentIndex(max(0, output_channel_order_idx))

                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)")
                self.mock_capture_checkbox.setChecked(
                    bool(getattr(cfg, "use_mock_capture", True))
                )
                self.mock_capture_checkbox.setToolTip("Use synthetic patterns for diagnostics without real screen capture.")

                self.capture_backend_combo = QComboBox()
                self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"])
                backend_idx = self.capture_backend_combo.findText(
                    str(getattr(cfg, "prefer_backend", "kwin-dbus"))
                )
                self.capture_backend_combo.setCurrentIndex(max(0, backend_idx))

                self.hdr_help = QLabel(
                    "HDR controls matter when your display/content is HDR. SDR users can keep defaults."
                )

                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq"])
                transfer_idx = self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))
                self.hdr_transfer_combo.setCurrentIndex(max(0, transfer_idx))

                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                primaries_idx = self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))
                self.hdr_primaries_combo.setCurrentIndex(max(0, primaries_idx))

                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(80, 4000)
                self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.led_gamma_slider.setRange(100, 400)
                self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 2.2) * 100)))

                self.calibration_help = QLabel(
                    "Zone alignment: use Reverse + Offset until the moving test pattern matches your strip."
                )
                self.preview_label = QLabel(
                    _mapping_preview_text(
                        zone_count=zone_count,
                        device_zone_count=device_zone_count,
                        zone_offset=int(getattr(cfg, "zone_offset", 0)),
                        reverse_zones=bool(getattr(cfg, "reverse_zones", False)),
                        auto_mapping=int(getattr(cfg, "device_zone_count", 0)) == 0,
                    )
                )
                self.brightness_value = QLabel("")
                self.smoothing_value = QLabel("")
                self.fps_value = QLabel("")
                self.zone_count_value = QLabel("")
                self.zone_offset_value = QLabel("")
                self.device_zone_count_value = QLabel("")
                self.hdr_max_nits_value = QLabel("")
                self.smoothing_speed_value = QLabel("")
                self.led_gamma_value = QLabel("")

                self._refresh_numeric_labels()
                self._refresh_preview_label()
                self.brightness_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.smoothing_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.smoothing_speed_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.fps_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                if hasattr(self.zone_preset_combo, "currentIndexChanged"):
                    self.zone_preset_combo.currentIndexChanged.connect(self._on_calibration_control_changed)
                self.zone_offset_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.device_zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.device_zone_count_auto_checkbox.stateChanged.connect(self._on_calibration_control_changed)
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.led_gamma_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.reverse_checkbox.stateChanged.connect(self._refresh_preview_label)

                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Save
                    | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QGridLayout()
                def _add_labeled(row: int, text: str, control, value_label=None, *, tooltip: str = "") -> None:
                    label = QLabel(text)
                    if tooltip:
                        if hasattr(label, "setToolTip"):
                            label.setToolTip(tooltip)
                        if hasattr(control, "setToolTip"):
                            control.setToolTip(tooltip)
                    layout.addWidget(label, row, 0)
                    layout.addWidget(control, row, 1)
                    if value_label is not None:
                        layout.addWidget(value_label, row, 2)

                _add_labeled(0, "Brightness", self.brightness_slider, self.brightness_value, tooltip="Controls LED output intensity without changing color balance.")
                _add_labeled(1, "Smoothing (min cutoff)", self.smoothing_slider, self.smoothing_value, tooltip="Higher smoothing reduces flicker but adds delay.")
                _add_labeled(2, "Smoothing speed coefficient", self.smoothing_speed_slider, self.smoothing_speed_value, tooltip="Makes smoothing react faster when colors change quickly.")
                _add_labeled(3, "Capture FPS", self.fps_slider, self.fps_value, tooltip="Higher values can reduce latency but use more CPU/GPU.")
                _add_labeled(4, "Colour mode", self.color_mode_combo, tooltip="Dynamic follows vivid or changing colours more aggressively.")
                _add_labeled(5, "Zone count", self.zone_count_slider, self.zone_count_value, tooltip="Number of sampled screen regions mapped to strip zones.")
                _add_labeled(6, "Zone preset", self.zone_preset_combo, tooltip="Edge-weighted tracks edges; horizontal splits into equal columns.")
                _add_labeled(7, "Zone offset (calibration)", self.zone_offset_slider, self.zone_offset_value, tooltip="Shift mapping until left/right screen movement matches strip direction.")
                layout.addWidget(self.reverse_checkbox, 8, 0, 1, 2)
                _add_labeled(9, "Device zone count", self.device_zone_count_slider, self.device_zone_count_value, tooltip="Set physical strip zone count, or use auto-detect.")
                layout.addWidget(self.device_zone_count_auto_checkbox, 10, 0, 1, 2)
                _add_labeled(11, "Output channel order", self.output_channel_order_combo, tooltip="Color channel order expected by your strip controller.")
                layout.addWidget(self.start_on_launch_checkbox, 12, 0, 1, 2)
                layout.addWidget(self.mock_capture_checkbox, 13, 0, 1, 2)
                _add_labeled(14, "Capture backend", self.capture_backend_combo, tooltip="Pick a capture backend, or keep auto for best available path.")
                layout.addWidget(self.calibration_help, 15, 0, 1, 2)
                layout.addWidget(self.preview_label, 16, 0, 1, 3)
                layout.addWidget(self.hdr_help, 17, 0, 1, 2)
                _add_labeled(18, "HDR transfer", self.hdr_transfer_combo, tooltip="Select source transfer curve for HDR capture paths.")
                _add_labeled(19, "HDR primaries", self.hdr_primaries_combo, tooltip="Select display primaries used for HDR color conversion.")
                _add_labeled(20, "HDR max nits", self.hdr_max_nits_slider, self.hdr_max_nits_value, tooltip="Peak luminance used for HDR tone mapping.")
                _add_labeled(21, "LED gamma", self.led_gamma_slider, self.led_gamma_value, tooltip="Compensates LED non-linearity for smoother gradients.")
                layout.addWidget(buttons, 22, 0, 1, 3)
                self.setLayout(layout)

            def _on_calibration_control_changed(self) -> None:
                self._refresh_numeric_labels()
                self._refresh_preview_label()

            def _refresh_numeric_labels(self) -> None:
                self.brightness_value.setText(f"{self.brightness_slider.value()}%")
                self.smoothing_value.setText(f"{self.smoothing_slider.value()}%")
                self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}")
                self.fps_value.setText(f"{self.fps_slider.value()} fps")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                if self.device_zone_count_auto_checkbox.isChecked():
                    self.device_zone_count_value.setText("auto")
                    if hasattr(self.device_zone_count_slider, "setEnabled"):
                        self.device_zone_count_slider.setEnabled(False)
                else:
                    self.device_zone_count_value.setText(str(self.device_zone_count_slider.value()))
                    if hasattr(self.device_zone_count_slider, "setEnabled"):
                        self.device_zone_count_slider.setEnabled(True)
                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
                self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}")

            def _refresh_preview_label(self) -> None:
                self.preview_label.setText(
                    _mapping_preview_text(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=(
                            int(self.zone_count_slider.value())
                            if self.device_zone_count_auto_checkbox.isChecked()
                            else int(self.device_zone_count_slider.value())
                        ),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                        auto_mapping=bool(self.device_zone_count_auto_checkbox.isChecked()),
                    )
                )

            def updated_config(self) -> AppConfig:
                brightness = self.brightness_slider.value() / 100.0
                smoothing = self.smoothing_slider.value() / 100.0
                smoothing_speed = self.smoothing_speed_slider.value() / 100.0
                fps = int(self.fps_slider.value())
                zone_count = int(self.zone_count_slider.value())
                zone_preset = str(self.zone_preset_combo.currentText())
                color_mode = str(self.color_mode_combo.currentText())
                zone_offset = int(self.zone_offset_slider.value())
                reverse_zones = bool(self.reverse_checkbox.isChecked())
                device_zone_count = 0 if self.device_zone_count_auto_checkbox.isChecked() else int(self.device_zone_count_slider.value())
                prefer_backend = str(self.capture_backend_combo.currentText())
                output_channel_order = str(self.output_channel_order_combo.currentText())
                hdr_transfer = str(self.hdr_transfer_combo.currentText())
                hdr_primaries = str(self.hdr_primaries_combo.currentText())
                hdr_max_nits = float(self.hdr_max_nits_slider.value())
                led_gamma = self.led_gamma_slider.value() / 100.0
                # Update zones from selected preset.
                new_zones = (
                    make_edge_weighted_zones(zone_count)
                    if zone_preset == "edge-weighted"
                    else make_horizontal_zones(zone_count)
                )
                # Preserve all other config fields; only override what the user changed.
                return replace(
                    cfg,
                    fps=fps,
                    brightness=brightness,
                    smoothing=smoothing,
                    smoothing_speed=smoothing_speed,
                    led_gamma=led_gamma,
                    zones=new_zones,
                    zone_preset=zone_preset,
                    color_mode=color_mode,
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()),
                    device_zone_count=device_zone_count,
                    output_channel_order=output_channel_order,
                    zone_offset=zone_offset,
                    reverse_zones=reverse_zones,
                    explicit_zone_map=[],
                    use_mock_capture=bool(self.mock_capture_checkbox.isChecked()),
                    prefer_backend=prefer_backend,
                    hdr_transfer=hdr_transfer,
                    hdr_primaries=hdr_primaries,
                    hdr_max_nits=hdr_max_nits,
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
