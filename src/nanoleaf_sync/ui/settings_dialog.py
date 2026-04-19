from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices

from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_horizontal_zones


def _mapping_preview_text(*, zone_count: int, device_zone_count: int, zone_offset: int, reverse_zones: bool) -> str:
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
    return f"Calibration preview (device→screen zones): {preview}{suffix}"


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

                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.fps_slider.setRange(1, 60)
                self.fps_slider.setValue(int(cfg.fps))

                # Derive zone_count from existing zones; if empty, default to 1.
                zone_count = len(cfg.zones) if cfg.zones else 1
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(int(zone_count))

                # Calibration controls (mapping sampled zones -> physical strip zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(int(getattr(cfg, "zone_offset", 0)))

                self.reverse_checkbox = QCheckBox("Reverse strip orientation")
                self.reverse_checkbox.setChecked(
                    bool(getattr(cfg, "reverse_zones", False))
                )

                device_zone_count = int(getattr(cfg, "device_zone_count", 0)) or int(
                    zone_count
                )
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(device_zone_count)

                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)")
                self.mock_capture_checkbox.setChecked(
                    bool(getattr(cfg, "use_mock_capture", True))
                )

                self.hdr_help = QLabel(
                    "HDR controls matter when your display/content is HDR. SDR users can keep defaults."
                )

                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq", "hlg"])
                transfer_idx = self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))
                self.hdr_transfer_combo.setCurrentIndex(max(0, transfer_idx))

                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                primaries_idx = self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))
                self.hdr_primaries_combo.setCurrentIndex(max(0, primaries_idx))

                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(80, 4000)
                self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))

                self.calibration_help = QLabel(
                    "Zone alignment: use Reverse + Offset until the moving test pattern matches your strip."
                )
                self.preview_label = QLabel(
                    _mapping_preview_text(
                        zone_count=zone_count,
                        device_zone_count=device_zone_count,
                        zone_offset=int(getattr(cfg, "zone_offset", 0)),
                        reverse_zones=bool(getattr(cfg, "reverse_zones", False)),
                    )
                )
                self.brightness_value = QLabel("")
                self.smoothing_value = QLabel("")
                self.fps_value = QLabel("")
                self.zone_count_value = QLabel("")
                self.zone_offset_value = QLabel("")
                self.device_zone_count_value = QLabel("")
                self.hdr_max_nits_value = QLabel("")

                self._refresh_numeric_labels()
                self._refresh_preview_label()
                self.brightness_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.smoothing_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.fps_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.zone_offset_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.device_zone_count_slider.valueChanged.connect(self._on_calibration_control_changed)
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.reverse_checkbox.stateChanged.connect(self._refresh_preview_label)

                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok
                    | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QGridLayout()
                layout.addWidget(QLabel("Brightness"), 0, 0)
                layout.addWidget(self.brightness_slider, 0, 1)
                layout.addWidget(self.brightness_value, 0, 2)
                layout.addWidget(QLabel("Smoothing (EMA alpha)"), 1, 0)
                layout.addWidget(self.smoothing_slider, 1, 1)
                layout.addWidget(self.smoothing_value, 1, 2)
                layout.addWidget(QLabel("Capture FPS"), 2, 0)
                layout.addWidget(self.fps_slider, 2, 1)
                layout.addWidget(self.fps_value, 2, 2)
                layout.addWidget(QLabel("Zone count (horizontal)"), 3, 0)
                layout.addWidget(self.zone_count_slider, 3, 1)
                layout.addWidget(self.zone_count_value, 3, 2)
                layout.addWidget(QLabel("Zone offset (calibration)"), 4, 0)
                layout.addWidget(self.zone_offset_slider, 4, 1)
                layout.addWidget(self.zone_offset_value, 4, 2)
                layout.addWidget(self.reverse_checkbox, 5, 0, 1, 2)
                layout.addWidget(QLabel("Device zone count"), 6, 0)
                layout.addWidget(self.device_zone_count_slider, 6, 1)
                layout.addWidget(self.device_zone_count_value, 6, 2)
                layout.addWidget(self.mock_capture_checkbox, 7, 0, 1, 2)
                layout.addWidget(self.calibration_help, 8, 0, 1, 2)
                layout.addWidget(self.preview_label, 9, 0, 1, 3)
                layout.addWidget(self.hdr_help, 10, 0, 1, 2)
                layout.addWidget(QLabel("HDR transfer"), 11, 0)
                layout.addWidget(self.hdr_transfer_combo, 11, 1)
                layout.addWidget(QLabel("HDR primaries"), 12, 0)
                layout.addWidget(self.hdr_primaries_combo, 12, 1)
                layout.addWidget(QLabel("HDR max nits"), 13, 0)
                layout.addWidget(self.hdr_max_nits_slider, 13, 1)
                layout.addWidget(self.hdr_max_nits_value, 13, 2)
                self.setLayout(layout)

            def _on_calibration_control_changed(self) -> None:
                self._refresh_numeric_labels()
                self._refresh_preview_label()

            def _refresh_numeric_labels(self) -> None:
                self.brightness_value.setText(f"{self.brightness_slider.value()}%")
                self.smoothing_value.setText(f"{self.smoothing_slider.value()}%")
                self.fps_value.setText(f"{self.fps_slider.value()} fps")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                self.device_zone_count_value.setText(str(self.device_zone_count_slider.value()))
                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")

            def _refresh_preview_label(self) -> None:
                self.preview_label.setText(
                    _mapping_preview_text(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=int(self.device_zone_count_slider.value()),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    )
                )

            def updated_config(self) -> AppConfig:
                brightness = self.brightness_slider.value() / 100.0
                smoothing = self.smoothing_slider.value() / 100.0
                fps = int(self.fps_slider.value())
                zone_count = int(self.zone_count_slider.value())
                zone_offset = int(self.zone_offset_slider.value())
                reverse_zones = bool(self.reverse_checkbox.isChecked())
                device_zone_count = int(self.device_zone_count_slider.value())
                hdr_transfer = str(self.hdr_transfer_combo.currentText())
                hdr_primaries = str(self.hdr_primaries_combo.currentText())
                hdr_max_nits = float(self.hdr_max_nits_slider.value())
                # Update zones as normalized equal slices.
                new_zones = make_horizontal_zones(zone_count)
                # Preserve all other config fields; only override what the user changed.
                return replace(
                    cfg,
                    fps=fps,
                    brightness=brightness,
                    smoothing=smoothing,
                    zones=new_zones,
                    device_zone_count=device_zone_count,
                    zone_offset=zone_offset,
                    reverse_zones=reverse_zones,
                    explicit_zone_map=[],
                    use_mock_capture=bool(self.mock_capture_checkbox.isChecked()),
                    prefer_backend="kwin-dbus",
                    hdr_transfer=hdr_transfer,
                    hdr_primaries=hdr_primaries,
                    hdr_max_nits=hdr_max_nits,
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
