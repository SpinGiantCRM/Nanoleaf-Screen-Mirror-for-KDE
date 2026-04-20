from __future__ import annotations

from dataclasses import replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_state import CalibrationState, TEST_MODES
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones


class DisplayConfiguratorDialog:
    """First-run display processing wizard."""

    def __init__(self, parent, cfg: AppConfig, *, calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QLabel = qt["QLabel"]
        QVBoxLayout = qt["QVBoxLayout"]
        QGridLayout = qt["QGridLayout"]
        QComboBox = qt["QComboBox"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Display Configurator")
                self._calibration_sender = calibration_sender
                self._test_step = 0
                self._state = CalibrationState.from_config(cfg)

                self.display_mode_combo = QComboBox()
                self.display_mode_combo.addItems(["sdr", "hdr"])
                self.display_mode_combo.setCurrentIndex(self.display_mode_combo.findText("hdr" if cfg.hdr_enabled else "sdr"))

                self.color_mode_combo = QComboBox()
                self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"])
                self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))))

                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq"])
                self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))))

                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))))

                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(80, 10000)
                self.hdr_max_nits_slider.setValue(min(int(getattr(cfg, "hdr_max_nits", 1000.0)), self.hdr_max_nits_slider.maximum()))
                self.hdr_max_nits_value = QLabel("")

                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_count_value = QLabel("")
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["edge-weighted", "horizontal"])
                self.zone_preset_combo.setCurrentIndex(max(0, self.zone_preset_combo.findText(self._state.zone_preset)))
                self.reverse_checkbox = qt["QCheckBox"]("Reverse strip orientation")
                self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(self._state.zone_offset)
                self.zone_offset_value = QLabel("")
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_auto_checkbox = qt["QCheckBox"]("Auto-detect strip zone count")
                self.device_zone_count_auto_checkbox.setChecked(self._state.auto_device_zone_count)
                self.preview_text = QLabel("")
                self.preview_visual = QLabel("")

                self.calibration_mode_combo = QComboBox()
                self.calibration_mode_combo.addItems(["coverage sanity", "direction walk", "corner+offset alignment"])
                self.calibration_test_label = QLabel("")
                self.calibration_next_button = QPushButton("Next test zone")
                self.calibration_prev_button = QPushButton("Previous")
                self.calibration_send_button = QPushButton("Send test pattern")

                self.cancel_button = QPushButton("Cancel")
                self.save_button = QPushButton("Save Display Setup")
                self.cancel_button.clicked.connect(self.reject)
                self.save_button.clicked.connect(self.accept)

                for signal in (
                    self.zone_count_slider.valueChanged,
                    self.zone_offset_slider.valueChanged,
                    self.zone_preset_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                    self.device_zone_count_slider.valueChanged,
                    self.device_zone_count_auto_checkbox.stateChanged,
                    self.calibration_mode_combo.currentIndexChanged,
                ):
                    signal.connect(self._refresh_mapping_preview)
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_count_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_offset_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.display_mode_combo.currentIndexChanged.connect(self._refresh_visibility)
                self.calibration_next_button.clicked.connect(self._next_test_zone)
                self.calibration_prev_button.clicked.connect(self._prev_test_zone)
                self.calibration_send_button.clicked.connect(self._send_test_pattern)

                layout = QVBoxLayout()
                layout.addWidget(QLabel("Step 1-3: choose display/HDR behavior."))
                step1 = QGridLayout()
                step1.addWidget(QLabel("SDR/HDR mode"), 0, 0)
                step1.addWidget(self.display_mode_combo, 0, 1)
                step1.addWidget(QLabel("Colour behaviour"), 1, 0)
                step1.addWidget(self.color_mode_combo, 1, 1)
                step1.addWidget(QLabel("HDR transfer"), 2, 0)
                step1.addWidget(self.hdr_transfer_combo, 2, 1)
                step1.addWidget(QLabel("HDR primaries"), 3, 0)
                step1.addWidget(self.hdr_primaries_combo, 3, 1)
                step1.addWidget(QLabel("HDR max brightness"), 4, 0)
                step1.addWidget(self.hdr_max_nits_slider, 4, 1)
                step1.addWidget(self.hdr_max_nits_value, 4, 2)
                layout.addLayout(step1)

                layout.addWidget(QLabel(f"Step 4: unified calibration controls\n{calibration_sequence_text()}"))
                step4 = QGridLayout()
                step4.addWidget(QLabel("Zone count"), 0, 0)
                step4.addWidget(self.zone_count_slider, 0, 1)
                step4.addWidget(self.zone_count_value, 0, 2)
                step4.addWidget(QLabel("Zone layout preset"), 1, 0)
                step4.addWidget(self.zone_preset_combo, 1, 1)
                step4.addWidget(QLabel("Zone offset"), 2, 0)
                step4.addWidget(self.zone_offset_slider, 2, 1)
                step4.addWidget(self.zone_offset_value, 2, 2)
                step4.addWidget(self.reverse_checkbox, 3, 0, 1, 2)
                step4.addWidget(QLabel("Device zone count"), 4, 0)
                step4.addWidget(self.device_zone_count_slider, 4, 1)
                step4.addWidget(self.device_zone_count_auto_checkbox, 5, 0, 1, 2)
                step4.addWidget(self.preview_text, 6, 0, 1, 3)
                step4.addWidget(self.preview_visual, 7, 0, 1, 3)
                step4.addWidget(QLabel("Calibration test mode"), 8, 0)
                step4.addWidget(self.calibration_mode_combo, 8, 1)
                step4.addWidget(self.calibration_next_button, 9, 0, 1, 2)
                step4.addWidget(self.calibration_prev_button, 9, 2)
                step4.addWidget(self.calibration_send_button, 10, 0, 1, 2)
                step4.addWidget(self.calibration_test_label, 11, 0, 1, 3)
                layout.addLayout(step4)

                actions = QGridLayout()
                actions.addWidget(self.cancel_button, 0, 0)
                actions.addWidget(self.save_button, 0, 1)
                layout.addLayout(actions)
                self.setLayout(layout)

                self._refresh_visibility()
                self._refresh_mapping_preview()

            def _pull_state_from_controls(self) -> None:
                self._state.zone_count = int(self.zone_count_slider.value())
                self._state.zone_preset = str(self.zone_preset_combo.currentText())
                self._state.zone_offset = int(self.zone_offset_slider.value())
                self._state.reverse_zones = bool(self.reverse_checkbox.isChecked())
                self._state.device_zone_count = int(self.device_zone_count_slider.value())
                self._state.auto_device_zone_count = bool(self.device_zone_count_auto_checkbox.isChecked())

            def _refresh_visibility(self) -> None:
                hdr_mode = str(self.display_mode_combo.currentText()) == "hdr"
                for widget in (self.hdr_transfer_combo, self.hdr_primaries_combo, self.hdr_max_nits_slider, self.hdr_max_nits_value):
                    widget.setVisible(hdr_mode)

            def _refresh_numeric_labels(self) -> None:
                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                self.device_zone_count_slider.setEnabled(not self.device_zone_count_auto_checkbox.isChecked())

            def _refresh_mapping_preview(self) -> None:
                self._pull_state_from_controls()
                self._refresh_numeric_labels()
                self.preview_text.setText(self._state.mapping_preview_text())
                self.preview_visual.setText(self._state.mapping_preview_visual())
                self.calibration_test_label.setText(self._state.step_for_mode(str(self.calibration_mode_combo.currentText()), self._test_step).label)

            def updated_config(self) -> AppConfig:
                self._pull_state_from_controls()
                zone_count = self._state.zone_count
                new_zones = make_edge_weighted_zones(zone_count) if self._state.zone_preset == "edge-weighted" else make_horizontal_zones(zone_count)
                return replace(
                    cfg,
                    hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    color_mode=str(self.color_mode_combo.currentText()),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    zones=new_zones,
                    zone_preset=self._state.zone_preset,
                    device_zone_count=0 if self._state.auto_device_zone_count else self._state.device_zone_count,
                    reverse_zones=self._state.reverse_zones,
                    zone_offset=self._state.zone_offset,
                    wizard_completed=True,
                )

            def _send_test_pattern(self) -> None:
                if self._calibration_sender is None:
                    return
                self._pull_state_from_controls()
                mode = str(self.calibration_mode_combo.currentText())
                self._calibration_sender(self._state.frame_for_step(mode=mode, step=self._test_step, brightness=1.0, all_off_except_active=True))

            def _next_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step + 1) % self._state.cycle_length(str(self.calibration_mode_combo.currentText()))
                self._refresh_mapping_preview()
                self._send_test_pattern()

            def _prev_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step - 1) % self._state.cycle_length(str(self.calibration_mode_combo.currentText()))
                self._refresh_mapping_preview()
                self._send_test_pattern()

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
