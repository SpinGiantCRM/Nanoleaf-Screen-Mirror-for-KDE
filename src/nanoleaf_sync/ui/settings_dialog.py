from __future__ import annotations

from dataclasses import replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    TEST_MODES,
    build_latency_result,
    latency_result_summary,
    next_corner_start_anchor,
    should_auto_run_latency_probe,
)
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text as _mapping_preview_text
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

FPS_MIN = 1
FPS_MAX = 120
HDR_MAX_NITS_MIN = 80
HDR_MAX_NITS_MAX = 10000
ZONE_STRIDE_MIN = 1
ZONE_STRIDE_MAX = 8


class SettingsDialog:
    def __init__(self, parent, cfg: AppConfig, *, calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None, runtime_status: dict | None = None):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QDialogButtonBox = qt["QDialogButtonBox"]
        QGridLayout = qt["QGridLayout"]
        QCheckBox = qt["QCheckBox"]
        QComboBox = qt["QComboBox"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]
        QTimer = qt["QTimer"]

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("nanoleaf-kde-sync Settings")
                self._open_display_configurator = False
                self._calibration_sender = calibration_sender
                self._state = CalibrationState.from_config(cfg, runtime_status)
                self._manual_map = self._state.explicit_zone_map[:]
                self._test_step = 0
                self._latest_latency = None

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.brightness_slider.setRange(0, 100); self.brightness_slider.setValue(int(round(cfg.brightness * 100)))
                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_slider.setRange(0, 100); self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))
                self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_speed_slider.setRange(0, 400); self.smoothing_speed_slider.setValue(int(round(getattr(cfg, "smoothing_speed", 0.75) * 100)))
                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.fps_slider.setRange(FPS_MIN, FPS_MAX); self.fps_slider.setValue(int(cfg.fps))
                self.display_mode_combo = QComboBox(); self.display_mode_combo.addItems(["sdr", "hdr"]); self.display_mode_combo.setCurrentIndex(1 if cfg.hdr_enabled else 0)
                self.color_mode_combo = QComboBox(); self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"]); self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))))
                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens"); self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))

                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_count_slider.setRange(1, 24); self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_preset_combo = QComboBox(); self.zone_preset_combo.addItems(["edge-weighted", "horizontal"]); self.zone_preset_combo.setCurrentIndex(max(0, self.zone_preset_combo.findText(self._state.zone_preset)))
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_offset_slider.setRange(-20, 20); self.zone_offset_slider.setValue(self._state.zone_offset)
                self.reverse_checkbox = QCheckBox("Reverse strip orientation"); self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.device_zone_count_slider.setRange(1, 128); self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_auto_checkbox = QCheckBox("Auto device zone count (match detected strip length)"); self.device_zone_count_auto_checkbox.setChecked(self._state.auto_device_zone_count)
                self.manual_map_checkbox = QCheckBox("Advanced: manual zone map"); self.manual_map_checkbox.setChecked(self._state.manual_mapping_enabled)
                self.manual_map_device_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.manual_map_device_slider.setRange(0, max(0, self._state.effective_device_zone_count() - 1)); self.manual_map_device_slider.setValue(0)
                self.manual_map_source_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.manual_map_source_slider.setRange(0, max(0, self._state.zone_count - 1)); self.manual_map_source_slider.setValue(0)
                self.manual_map_apply_button = QPushButton("Apply mapping for selected strip zone")
                self.corner_anchor_button = QPushButton("Set next top-left anchor")

                self.test_step_button = QPushButton("Next test zone"); self.test_prev_button = QPushButton("Previous test zone"); self.test_send_button = QPushButton("Send test pattern")
                self.test_mode_combo = QComboBox(); self.test_mode_combo.addItems(list(TEST_MODES))
                self.test_auto_checkbox = QCheckBox("Auto-step")
                self.test_loop_checkbox = QCheckBox("Loop"); self.test_loop_checkbox.setChecked(True)
                self.test_duration_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_duration_slider.setRange(1, 60); self.test_duration_slider.setValue(12)
                self.test_step_interval_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_step_interval_slider.setRange(100, 2000); self.test_step_interval_slider.setValue(500)
                self.test_brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_brightness_slider.setRange(5, 100); self.test_brightness_slider.setValue(100)
                self.test_background_checkbox = QCheckBox("All off except active zone"); self.test_background_checkbox.setChecked(True)
                self._test_elapsed_ms = 0
                self._test_timer = QTimer(self); self._test_timer.timeout.connect(self._on_test_timer_tick)

                self.output_channel_order_combo = QComboBox(); self.output_channel_order_combo.addItems(["grb", "rgb", "rbg", "gbr", "brg", "bgr"]); self.output_channel_order_combo.setCurrentIndex(max(0, self.output_channel_order_combo.findText(str(getattr(cfg, "output_channel_order", "grb")))))
                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)"); self.mock_capture_checkbox.setChecked(bool(getattr(cfg, "use_mock_capture", True)))
                self.capture_backend_combo = QComboBox(); self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"]); self.capture_backend_combo.setCurrentIndex(max(0, self.capture_backend_combo.findText(str(getattr(cfg, "prefer_backend", "kwin-dbus")))))
                self.auto_probe_policy_combo = QComboBox(); self.auto_probe_policy_combo.addItems(["on-change", "first-run", "each-boot"]); self.auto_probe_policy_combo.setCurrentIndex(max(0, self.auto_probe_policy_combo.findText(str(getattr(cfg, "auto_probe_policy", "on-change")))))

                self.auto_latency_policy_combo = QComboBox(); self.auto_latency_policy_combo.addItems(["manual", "on-open", "on-open-once-per-backend"]); self.auto_latency_policy_combo.setCurrentIndex(max(0, self.auto_latency_policy_combo.findText(str(getattr(cfg, "auto_latency_policy", "manual")))))
                self.run_latency_button = QPushButton("Run latency checker now")
                self.latency_label = QLabel(latency_result_summary(None))

                self.hdr_transfer_combo = QComboBox(); self.hdr_transfer_combo.addItems(["srgb", "pq"]); self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))))
                self.hdr_primaries_combo = QComboBox(); self.hdr_primaries_combo.addItems(["bt709", "bt2020"]); self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))))
                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.hdr_max_nits_slider.setRange(HDR_MAX_NITS_MIN, HDR_MAX_NITS_MAX); self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))
                self.zone_sampling_stride_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_sampling_stride_slider.setRange(ZONE_STRIDE_MIN, ZONE_STRIDE_MAX); self.zone_sampling_stride_slider.setValue(int(getattr(cfg, "zone_sampling_stride", 1)))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.led_gamma_slider.setRange(100, 400); self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 1.0) * 100)))
                self.display_configurator_button = QPushButton("Re-run Display Setup"); self.display_configurator_button.clicked.connect(self._open_configurator)

                self.preview_label = QLabel(""); self.preview_visual_label = QLabel(""); self.test_label = QLabel("")
                self.brightness_value = QLabel(""); self.smoothing_value = QLabel(""); self.fps_value = QLabel(""); self.zone_count_value = QLabel(""); self.zone_offset_value = QLabel(""); self.device_zone_count_value = QLabel(""); self.hdr_max_nits_value = QLabel(""); self.zone_sampling_stride_value = QLabel(""); self.smoothing_speed_value = QLabel(""); self.led_gamma_value = QLabel(""); self.test_duration_value = QLabel(""); self.test_step_interval_value = QLabel(""); self.test_brightness_value = QLabel("")

                for signal in (self.zone_count_slider.valueChanged, self.zone_preset_combo.currentIndexChanged, self.zone_offset_slider.valueChanged, self.device_zone_count_slider.valueChanged, self.device_zone_count_auto_checkbox.stateChanged, self.reverse_checkbox.stateChanged, self.manual_map_checkbox.stateChanged):
                    signal.connect(self._refresh_preview_label)
                self.manual_map_device_slider.valueChanged.connect(self._sync_manual_source_slider)
                self.manual_map_apply_button.clicked.connect(self._apply_manual_mapping)
                self.corner_anchor_button.clicked.connect(self._rotate_anchor)
                self.test_step_button.clicked.connect(self._step_test_zone); self.test_prev_button.clicked.connect(self._prev_test_zone); self.test_send_button.clicked.connect(self._send_test_pattern)
                self.test_auto_checkbox.stateChanged.connect(self._on_test_auto_toggled); self.test_mode_combo.currentIndexChanged.connect(self._refresh_preview_label)
                self.test_step_interval_slider.valueChanged.connect(self._on_interval_changed)
                self.run_latency_button.clicked.connect(self._run_latency_probe_manual)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
                layout = QGridLayout()

                def _add(row: int, text: str, control, value=None):
                    layout.addWidget(QLabel(text), row, 0); layout.addWidget(control, row, 1)
                    if value is not None: layout.addWidget(value, row, 2)

                layout.addWidget(QLabel("Display / Image Behaviour"), 0, 0, 1, 2)
                _add(1, "SDR/HDR mode", self.display_mode_combo); _add(2, "Colour behaviour preset", self.color_mode_combo)
                _add(3, "HDR transfer", self.hdr_transfer_combo); _add(4, "HDR primaries", self.hdr_primaries_combo); _add(5, "HDR max brightness", self.hdr_max_nits_slider, self.hdr_max_nits_value)
                layout.addWidget(self.display_configurator_button, 6, 0, 1, 2)
                layout.addWidget(QLabel("Runtime / Performance"), 7, 0, 1, 2)
                _add(8, "Brightness", self.brightness_slider, self.brightness_value); _add(9, "Smoothing", self.smoothing_slider, self.smoothing_value); _add(10, "Smoothing speed", self.smoothing_speed_slider, self.smoothing_speed_value); _add(11, "Capture FPS", self.fps_slider, self.fps_value); _add(12, "Zone sampling stride", self.zone_sampling_stride_slider, self.zone_sampling_stride_value)
                layout.addWidget(QLabel("Calibration / Testing (shared model)"), 13, 0, 1, 3)
                layout.addWidget(QLabel(f"Calibration sequence:\n{calibration_sequence_text()}"), 14, 0, 1, 3)
                _add(15, "Zone count", self.zone_count_slider, self.zone_count_value); _add(16, "Zone layout preset", self.zone_preset_combo); _add(17, "Start offset (rotation)", self.zone_offset_slider, self.zone_offset_value)
                layout.addWidget(self.reverse_checkbox, 18, 0, 1, 2); _add(19, "Device zone count", self.device_zone_count_slider, self.device_zone_count_value); layout.addWidget(self.device_zone_count_auto_checkbox, 20, 0, 1, 2)
                _add(21, "Test mode", self.test_mode_combo); layout.addWidget(self.test_step_button, 22, 0, 1, 2); layout.addWidget(self.test_prev_button, 22, 2, 1, 1)
                layout.addWidget(self.test_auto_checkbox, 23, 0, 1, 1); layout.addWidget(self.test_loop_checkbox, 23, 1, 1, 1); _add(24, "Test duration (s)", self.test_duration_slider, self.test_duration_value); _add(25, "Step interval (ms)", self.test_step_interval_slider, self.test_step_interval_value); _add(26, "Test brightness", self.test_brightness_slider, self.test_brightness_value)
                layout.addWidget(self.test_background_checkbox, 27, 0, 1, 2); layout.addWidget(self.test_send_button, 28, 0, 1, 2); layout.addWidget(self.test_label, 29, 0, 1, 3)
                layout.addWidget(self.manual_map_checkbox, 30, 0, 1, 2); _add(31, "Manual map: strip zone", self.manual_map_device_slider); _add(32, "Manual map: screen zone", self.manual_map_source_slider); layout.addWidget(self.manual_map_apply_button, 33, 0, 1, 2); layout.addWidget(self.corner_anchor_button, 34, 0, 1, 2)
                _add(35, "Output channel order", self.output_channel_order_combo)
                layout.addWidget(self.start_on_launch_checkbox, 36, 0, 1, 2); layout.addWidget(self.mock_capture_checkbox, 37, 0, 1, 2); _add(38, "Capture backend", self.capture_backend_combo); _add(39, "Auto-probe policy", self.auto_probe_policy_combo); _add(40, "Latency auto-run policy", self.auto_latency_policy_combo)
                layout.addWidget(self.run_latency_button, 41, 0, 1, 2); layout.addWidget(self.latency_label, 42, 0, 1, 3)
                _add(43, "LED gamma", self.led_gamma_slider, self.led_gamma_value)
                layout.addWidget(self.preview_label, 44, 0, 1, 3); layout.addWidget(self.preview_visual_label, 45, 0, 1, 3); layout.addWidget(buttons, 46, 0, 1, 3)
                self.setLayout(layout)

                self._refresh_numeric_labels(); self._refresh_preview_label(); self._maybe_auto_run_latency_check()

            def _open_configurator(self): self._open_display_configurator = True; self.accept()
            def wants_display_configurator(self) -> bool: return bool(self._open_display_configurator)

            def _pull_state(self):
                self._state.zone_count = int(self.zone_count_slider.value()); self._state.zone_preset = str(self.zone_preset_combo.currentText()); self._state.zone_offset = int(self.zone_offset_slider.value()); self._state.reverse_zones = bool(self.reverse_checkbox.isChecked()); self._state.device_zone_count = int(self.device_zone_count_slider.value()); self._state.auto_device_zone_count = bool(self.device_zone_count_auto_checkbox.isChecked()); self._state.manual_mapping_enabled = bool(self.manual_map_checkbox.isChecked()); self._state.explicit_zone_map = self._manual_map[:]

            def _refresh_numeric_labels(self):
                self.brightness_value.setText(f"{self.brightness_slider.value()}%"); self.smoothing_value.setText(f"{self.smoothing_slider.value()}%"); self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}"); self.fps_value.setText(f"{self.fps_slider.value()} fps"); self.zone_sampling_stride_value.setText(str(self.zone_sampling_stride_slider.value())); self.zone_count_value.setText(str(self.zone_count_slider.value())); self.zone_offset_value.setText(str(self.zone_offset_slider.value())); self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits"); self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}"); self.test_duration_value.setText(str(self.test_duration_slider.value())); self.test_step_interval_value.setText(str(self.test_step_interval_slider.value())); self.test_brightness_value.setText(f"{self.test_brightness_slider.value()}%")

            def _refresh_preview_label(self):
                self._refresh_numeric_labels(); self._pull_state()
                self.device_zone_count_slider.setEnabled(not self.device_zone_count_auto_checkbox.isChecked())
                self.device_zone_count_value.setText("auto" if self.device_zone_count_auto_checkbox.isChecked() else str(self.device_zone_count_slider.value()))
                self.manual_map_device_slider.setRange(0, max(0, self._state.effective_device_zone_count() - 1)); self.manual_map_source_slider.setRange(0, max(0, self._state.zone_count - 1)); enabled = self.manual_map_checkbox.isChecked(); self.manual_map_device_slider.setEnabled(enabled); self.manual_map_source_slider.setEnabled(enabled); self.manual_map_apply_button.setEnabled(enabled)
                self.preview_label.setText(self._state.mapping_preview_text()); self.preview_visual_label.setText(self._state.mapping_preview_visual()); self.test_label.setText(self._current_calibration_step().label)

            def _sync_manual_source_slider(self):
                idx = int(self.manual_map_device_slider.value())
                self.manual_map_source_slider.setValue(int(self._manual_map[idx]) if idx < len(self._manual_map) else 0)

            def _apply_manual_mapping(self):
                idx = int(self.manual_map_device_slider.value()); val = int(self.manual_map_source_slider.value())
                if idx >= len(self._manual_map): self._manual_map.extend([0] * (idx + 1 - len(self._manual_map)))
                self._manual_map[idx] = val; self._refresh_preview_label()

            def _rotate_anchor(self):
                self._pull_state(); self._state.corner_start_anchor = next_corner_start_anchor(self._state.corner_start_anchor, device_zone_count=self._state.effective_device_zone_count()); self._refresh_preview_label()

            def _current_calibration_step(self): return self._state.step_for_mode(str(self.test_mode_combo.currentText()), self._test_step)
            def _test_cycle_length(self): return self._state.cycle_length(str(self.test_mode_combo.currentText()))
            def _step_test_zone(self): self._test_step = (self._test_step + 1) % self._test_cycle_length(); self._refresh_preview_label(); self._send_test_pattern()
            def _prev_test_zone(self): self._test_step = (self._test_step - 1) % self._test_cycle_length(); self._refresh_preview_label(); self._send_test_pattern()

            def _send_test_pattern(self):
                if self._calibration_sender is None: return
                self._pull_state()
                colors = self._state.frame_for_step(mode=str(self.test_mode_combo.currentText()), step=self._test_step, brightness=self.test_brightness_slider.value()/100.0, all_off_except_active=bool(self.test_background_checkbox.isChecked()))
                self._calibration_sender(colors)

            def _on_test_auto_toggled(self):
                self._test_elapsed_ms = 0
                if self.test_auto_checkbox.isChecked(): self._test_timer.start(max(100, int(self.test_step_interval_slider.value())))
                else: self._test_timer.stop()

            def _on_test_timer_tick(self):
                self._test_elapsed_ms += max(100, int(self.test_step_interval_slider.value()))
                if self._test_elapsed_ms >= int(self.test_duration_slider.value()) * 1000:
                    if self.test_loop_checkbox.isChecked(): self._test_elapsed_ms = 0; self._test_step = 0
                    else: self.test_auto_checkbox.setChecked(False); self._test_timer.stop(); return
                self._step_test_zone()

            def _on_interval_changed(self):
                if self._test_timer.isActive(): self._test_timer.setInterval(max(100, int(self.test_step_interval_slider.value())))

            def _active_backend(self) -> str:
                return str((runtime_status or {}).get("effective_capture_backend") or (runtime_status or {}).get("capture_backend") or str(self.capture_backend_combo.currentText()))

            def _run_latency_probe_manual(self):
                self._latest_latency = build_latency_result(backend=self._active_backend(), measured_latency_ms=1000.0 / max(1, int(self.fps_slider.value())), triggered_by="manual", details="Estimated from configured capture FPS")
                self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _maybe_auto_run_latency_check(self):
                if should_auto_run_latency_probe(policy=str(self.auto_latency_policy_combo.currentText()), last_result=self._latest_latency, active_backend=self._active_backend()):
                    self._latest_latency = build_latency_result(backend=self._active_backend(), measured_latency_ms=1000.0 / max(1, int(self.fps_slider.value())), triggered_by="auto", details="Auto-run on settings open")
                    self.latency_label.setText(latency_result_summary(self._latest_latency))

            def updated_config(self) -> AppConfig:
                self._pull_state()
                new_zones = make_edge_weighted_zones(self._state.zone_count) if self._state.zone_preset == "edge-weighted" else make_horizontal_zones(self._state.zone_count)
                return replace(
                    cfg,
                    fps=int(self.fps_slider.value()), zone_sampling_stride=int(self.zone_sampling_stride_slider.value()), brightness=self.brightness_slider.value() / 100.0,
                    smoothing=self.smoothing_slider.value() / 100.0, smoothing_speed=self.smoothing_speed_slider.value() / 100.0, led_gamma=self.led_gamma_slider.value() / 100.0,
                    zones=new_zones, zone_preset=self._state.zone_preset, color_mode=str(self.color_mode_combo.currentText()), hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()), device_zone_count=0 if self._state.auto_device_zone_count else self._state.device_zone_count,
                    output_channel_order=str(self.output_channel_order_combo.currentText()), zone_offset=self._state.zone_offset, reverse_zones=self._state.reverse_zones,
                    explicit_zone_map=(self._manual_map[: self._state.effective_device_zone_count()] if self._state.manual_mapping_enabled else []),
                    corner_start_anchor=int(self._state.corner_start_anchor), use_mock_capture=bool(self.mock_capture_checkbox.isChecked()), prefer_backend=str(self.capture_backend_combo.currentText()), auto_probe_policy=str(self.auto_probe_policy_combo.currentText()), auto_latency_policy=str(self.auto_latency_policy_combo.currentText()),
                    latency_last_backend=(self._latest_latency.backend if self._latest_latency else getattr(cfg, "latency_last_backend", "")),
                    latency_last_value_ms=(self._latest_latency.measured_latency_ms if self._latest_latency else float(getattr(cfg, "latency_last_value_ms", 0.0))),
                    latency_last_trigger=(self._latest_latency.triggered_by if self._latest_latency else getattr(cfg, "latency_last_trigger", "")),
                    latency_last_timestamp=(self._latest_latency.recorded_at_utc if self._latest_latency else getattr(cfg, "latency_last_timestamp", "")),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()), hdr_primaries=str(self.hdr_primaries_combo.currentText()), hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                )

        self._dialog = _Dialog()

    def exec(self) -> int: return self._dialog.exec()
    def updated_config(self) -> AppConfig: return self._dialog.updated_config()
    def wants_display_configurator(self) -> bool: return bool(self._dialog.wants_display_configurator())
