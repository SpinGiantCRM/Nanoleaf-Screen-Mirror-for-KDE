from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig

from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_horizontal_zones


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

                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok
                    | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QGridLayout()
                layout.addWidget(QLabel("Brightness"), 0, 0)
                layout.addWidget(self.brightness_slider, 0, 1)
                layout.addWidget(QLabel("Smoothing (EMA alpha)"), 1, 0)
                layout.addWidget(self.smoothing_slider, 1, 1)
                layout.addWidget(QLabel("Capture FPS"), 2, 0)
                layout.addWidget(self.fps_slider, 2, 1)
                layout.addWidget(QLabel("Zone count (horizontal)"), 3, 0)
                layout.addWidget(self.zone_count_slider, 3, 1)
                layout.addWidget(QLabel("Zone offset (calibration)"), 4, 0)
                layout.addWidget(self.zone_offset_slider, 4, 1)
                layout.addWidget(self.reverse_checkbox, 5, 0, 1, 2)
                layout.addWidget(QLabel("Device zone count"), 6, 0)
                layout.addWidget(self.device_zone_count_slider, 6, 1)
                layout.addWidget(self.mock_capture_checkbox, 7, 0, 1, 2)
                layout.addWidget(buttons, 8, 0, 1, 2)
                self.setLayout(layout)

            def updated_config(self) -> AppConfig:
                brightness = self.brightness_slider.value() / 100.0
                smoothing = self.smoothing_slider.value() / 100.0
                fps = int(self.fps_slider.value())
                zone_count = int(self.zone_count_slider.value())
                zone_offset = int(self.zone_offset_slider.value())
                reverse_zones = bool(self.reverse_checkbox.isChecked())
                device_zone_count = int(self.device_zone_count_slider.value())

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
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
