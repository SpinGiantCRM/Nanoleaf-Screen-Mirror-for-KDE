from __future__ import annotations

from dataclasses import dataclass
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
    backend_selection_info,
)
from nanoleaf_sync.ui.qt_lazy import load_qt


@dataclass
class DiagnosticsSnapshot:
    requested_backend: str
    effective_backend: str
    selection_reason: str
    from_auto_probe: bool
    auto_probe_timestamp: str
    detected_device_zone_count: int
    configured_device_zone_count: int


class CalibrationDiagnosticsDialog:
    def __init__(self, parent, *, cfg: AppConfig, runtime_status: dict, calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None) -> None:
        qt = load_qt()
        QDialog = qt["QDialog"]; QGridLayout = qt["QGridLayout"]; QLabel = qt["QLabel"]; QSlider = qt["QSlider"]; QPushButton = qt["QPushButton"]; QComboBox = qt["QComboBox"]; QCheckBox = qt["QCheckBox"]; QTimer = qt["QTimer"]

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Calibration / Testing")
                self._cfg = cfg; self._status = runtime_status; self._sender = calibration_sender; self._step = 0; self._elapsed_ms = 0; self._auto_timer = QTimer(self); self._auto_timer.timeout.connect(self._on_auto_step_tick)
                self._state = CalibrationState.from_config(cfg, runtime_status)
                self._latest_latency = None

                self.mode_combo = QComboBox(); self.mode_combo.addItems(list(TEST_MODES))
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_offset_slider.setRange(-20, 20); self.zone_offset_slider.setValue(self._state.zone_offset)
                self.reverse_checkbox = QCheckBox("Reverse strip orientation"); self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.anchor_button = QPushButton("Set next top-left anchor")
                self.corner_offsets_enabled_checkbox = QCheckBox("Enable advanced corner refinement")
                self.corner_offsets_enabled_checkbox.setChecked(self._state.corner_offsets_enabled)
                self.corner_offset_sliders = []
                for idx in range(4):
                    slider = QSlider(qt["Qt"].Orientation.Horizontal)
                    slider.setRange(-8, 8)
                    slider.setValue(int(self._state.active_corner_zone_offsets()[idx]))
                    self.corner_offset_sliders.append(slider)
                self.duration_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.duration_slider.setRange(1, 60); self.duration_slider.setValue(15)
                self.interval_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.interval_slider.setRange(100, 2000); self.interval_slider.setValue(400)
                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.brightness_slider.setRange(5, 100); self.brightness_slider.setValue(int(cfg.brightness * 100))
                self.loop_checkbox = QCheckBox("Loop"); self.loop_checkbox.setChecked(True)
                self.auto_step_checkbox = QCheckBox("Auto-step")
                self.off_except_active_checkbox = QCheckBox("All off except active zone"); self.off_except_active_checkbox.setChecked(True)
                self.prev_button = QPushButton("Previous zone"); self.next_button = QPushButton("Next zone"); self.send_button = QPushButton("Send now")
                self.auto_latency_policy_combo = QComboBox(); self.auto_latency_policy_combo.addItems(["manual", "on-open", "on-open-once-per-backend"]); self.auto_latency_policy_combo.setCurrentIndex(max(0, self.auto_latency_policy_combo.findText(str(getattr(cfg, "auto_latency_policy", "manual")))))
                self.run_latency_button = QPushButton("Run latency checker")

                self.status_label = QLabel(""); self.debug_label = QLabel(""); self.sequence_label = QLabel(calibration_sequence_text()); self.test_label = QLabel(""); self.progress_label = QLabel(""); self.latency_label = QLabel(latency_result_summary(None))

                self.prev_button.clicked.connect(self._prev); self.next_button.clicked.connect(self._next); self.send_button.clicked.connect(self._send)
                self.mode_combo.currentIndexChanged.connect(self._refresh); self.zone_offset_slider.valueChanged.connect(self._refresh); self.reverse_checkbox.stateChanged.connect(self._refresh)
                self.corner_offsets_enabled_checkbox.stateChanged.connect(self._refresh)
                for slider in self.corner_offset_sliders:
                    slider.valueChanged.connect(self._refresh)
                self.duration_slider.valueChanged.connect(self._refresh); self.interval_slider.valueChanged.connect(self._refresh); self.brightness_slider.valueChanged.connect(self._refresh); self.interval_slider.valueChanged.connect(self._on_interval_changed)
                self.auto_step_checkbox.stateChanged.connect(self._on_auto_step_toggled); self.run_latency_button.clicked.connect(self._run_latency_manual); self.anchor_button.clicked.connect(self._advance_anchor)

                layout = QGridLayout()
                layout.addWidget(QLabel("Backend selection"), 0, 0, 1, 3); layout.addWidget(self.status_label, 1, 0, 1, 3); layout.addWidget(self.debug_label, 2, 0, 1, 3)
                layout.addWidget(QLabel("Calibration sequence"), 3, 0, 1, 3); layout.addWidget(self.sequence_label, 4, 0, 1, 3)
                layout.addWidget(QLabel("Test mode"), 5, 0); layout.addWidget(self.mode_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Offset"), 6, 0); layout.addWidget(self.zone_offset_slider, 6, 1, 1, 2); layout.addWidget(self.reverse_checkbox, 7, 0, 1, 2)
                layout.addWidget(self.corner_offsets_enabled_checkbox, 8, 0, 1, 3)
                layout.addWidget(QLabel("Top-left / top-right"), 9, 0); layout.addWidget(self.corner_offset_sliders[0], 9, 1); layout.addWidget(self.corner_offset_sliders[1], 9, 2)
                layout.addWidget(QLabel("Bottom-right / bottom-left"), 10, 0); layout.addWidget(self.corner_offset_sliders[2], 10, 1); layout.addWidget(self.corner_offset_sliders[3], 10, 2)
                layout.addWidget(self.anchor_button, 11, 0, 1, 2)
                layout.addWidget(QLabel("Test duration (s)"), 12, 0); layout.addWidget(self.duration_slider, 12, 1, 1, 2); layout.addWidget(QLabel("Step interval (ms)"), 13, 0); layout.addWidget(self.interval_slider, 13, 1, 1, 2)
                layout.addWidget(QLabel("Test brightness"), 14, 0); layout.addWidget(self.brightness_slider, 14, 1, 1, 2)
                layout.addWidget(self.loop_checkbox, 15, 0, 1, 2); layout.addWidget(self.auto_step_checkbox, 16, 0, 1, 2); layout.addWidget(self.off_except_active_checkbox, 17, 0, 1, 2)
                layout.addWidget(self.prev_button, 18, 0); layout.addWidget(self.next_button, 18, 1); layout.addWidget(self.send_button, 18, 2)
                layout.addWidget(self.test_label, 19, 0, 1, 3); layout.addWidget(self.progress_label, 20, 0, 1, 3)
                layout.addWidget(QLabel("Latency checker"), 21, 0, 1, 3); layout.addWidget(self.auto_latency_policy_combo, 22, 0, 1, 2); layout.addWidget(self.run_latency_button, 23, 0, 1, 2); layout.addWidget(self.latency_label, 24, 0, 1, 3)
                self.setLayout(layout)
                self._restore_latency_from_cfg(); self._refresh(); self._maybe_auto_latency()

            def _restore_latency_from_cfg(self):
                if float(getattr(self._cfg, "latency_last_value_ms", 0.0)) > 0:
                    info = backend_selection_info(self._status, self._cfg)
                    self._latest_latency = build_latency_result(requested_policy=info.requested_policy, selected_backend=str(getattr(self._cfg, "latency_last_backend", "unknown")), selection_source=info.source, selection_reason=info.reason, measured_latency_ms=float(getattr(self._cfg, "latency_last_value_ms", 0.0)), measurement_kind="estimated", confidence_note="Persisted estimate from prior run", triggered_by=str(getattr(self._cfg, "latency_last_trigger", "unknown")), details="persisted result")
                    self._latest_latency.recorded_at_utc = str(getattr(self._cfg, "latency_last_timestamp", "")) or self._latest_latency.recorded_at_utc
                    self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _snapshot(self) -> DiagnosticsSnapshot:
                return DiagnosticsSnapshot(
                    requested_backend=str(self._status.get("requested_capture_backend") or self._cfg.prefer_backend),
                    effective_backend=str(self._status.get("effective_capture_backend") or self._status.get("capture_backend") or "unknown"),
                    selection_reason=str(self._status.get("selection_reason") or "unknown"),
                    from_auto_probe=bool(self._status.get("from_auto_probe")),
                    auto_probe_timestamp=str(getattr(self._cfg, "auto_probe_timestamp", "") or "n/a"),
                    detected_device_zone_count=int(self._status.get("device_zone_count") or 0),
                    configured_device_zone_count=int(self._cfg.device_zone_count or 0),
                )

            def _refresh_state(self):
                self._state.zone_offset = int(self.zone_offset_slider.value()); self._state.reverse_zones = bool(self.reverse_checkbox.isChecked()); self._state.corner_offsets_enabled = bool(self.corner_offsets_enabled_checkbox.isChecked()); self._state.corner_zone_offsets = [int(slider.value()) for slider in self.corner_offset_sliders]

            def _active_backend(self) -> str: return str(self._status.get("effective_capture_backend") or self._cfg.prefer_backend)
            def _current_step(self): self._refresh_state(); return self._state.step_for_mode(str(self.mode_combo.currentText()), self._step)

            def _refresh(self):
                snapshot = self._snapshot(); self.status_label.setText(f"Requested backend: {snapshot.requested_backend} | Effective: {snapshot.effective_backend} | Reason: {snapshot.selection_reason}")
                self.debug_label.setText(f"From auto probe: {snapshot.from_auto_probe} | Auto probe timestamp: {snapshot.auto_probe_timestamp} | Detected strip zones: {snapshot.detected_device_zone_count or 'unknown'} | Configured strip zones: {snapshot.configured_device_zone_count or 'auto'}")
                self.test_label.setText(self._current_step().label)
                self.progress_label.setText(f"Step {self._step + 1}/{self._state.cycle_length(str(self.mode_combo.currentText()))}")

            def _send(self):
                if self._sender is None: return
                self._refresh_state()
                self._sender(self._state.frame_for_step(mode=str(self.mode_combo.currentText()), step=self._step, brightness=self.brightness_slider.value()/100.0, all_off_except_active=bool(self.off_except_active_checkbox.isChecked())))

            def _next(self): self._step = (self._step + 1) % self._state.cycle_length(str(self.mode_combo.currentText())); self._refresh(); self._send()
            def _prev(self): self._step = (self._step - 1) % self._state.cycle_length(str(self.mode_combo.currentText())); self._refresh(); self._send()
            def _advance_anchor(self): self._state.corner_start_anchor = next_corner_start_anchor(self._state.corner_start_anchor, device_zone_count=self._state.effective_device_zone_count()); self._refresh()

            def _on_interval_changed(self):
                if self._auto_timer.isActive(): self._auto_timer.setInterval(max(100, int(self.interval_slider.value())))

            def _on_auto_step_toggled(self):
                self._elapsed_ms = 0
                if self.auto_step_checkbox.isChecked(): self._auto_timer.start(max(100, int(self.interval_slider.value())))
                else: self._auto_timer.stop()

            def _on_auto_step_tick(self):
                self._elapsed_ms += max(100, int(self.interval_slider.value()))
                if self._elapsed_ms >= int(self.duration_slider.value()) * 1000:
                    if self.loop_checkbox.isChecked(): self._elapsed_ms = 0; self._step = 0
                    else: self.auto_step_checkbox.setChecked(False); self._auto_timer.stop(); return
                self._next()

            def _run_latency_manual(self):
                info = backend_selection_info(self._status, self._cfg)
                self._latest_latency = build_latency_result(requested_policy=info.requested_policy, selected_backend=self._active_backend(), selection_source=info.source, selection_reason=info.reason, measured_latency_ms=1000.0 / max(1, int(getattr(self._cfg, "fps", 30))), measurement_kind="estimated", confidence_note="Derived from configured FPS; not hardware measured", triggered_by="manual", details="Manual latency estimate")
                self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _maybe_auto_latency(self):
                if should_auto_run_latency_probe(policy=str(self.auto_latency_policy_combo.currentText()), last_result=self._latest_latency, active_backend=self._active_backend()):
                    info = backend_selection_info(self._status, self._cfg)
                    self._latest_latency = build_latency_result(requested_policy=info.requested_policy, selected_backend=self._active_backend(), selection_source=info.source, selection_reason=info.reason, measured_latency_ms=1000.0 / max(1, int(getattr(self._cfg, "fps", 30))), measurement_kind="estimated", confidence_note="Auto policy estimate from configured FPS", triggered_by="auto", details="Auto-run per policy")
                    self.latency_label.setText(latency_result_summary(self._latest_latency))

        self._dialog = _Dialog()

    def exec(self) -> int: return self._dialog.exec()
    def show(self) -> None: self._dialog.show()
    def raise_(self) -> None: self._dialog.raise_()
    def activateWindow(self) -> None: self._dialog.activateWindow()
    def set_runtime_status(self, runtime_status: dict) -> None: self._dialog._status = runtime_status; self._dialog._refresh()
