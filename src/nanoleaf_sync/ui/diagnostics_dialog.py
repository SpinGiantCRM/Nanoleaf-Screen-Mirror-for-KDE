from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_preview import calibration_test_frame, corner_anchor_steps, coverage_sanity_step, single_zone_step
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
    def __init__(
        self,
        parent,
        *,
        cfg: AppConfig,
        runtime_status: dict,
        calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None,
    ) -> None:
        qt = load_qt()
        QDialog = qt["QDialog"]
        QGridLayout = qt["QGridLayout"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]
        QComboBox = qt["QComboBox"]
        QCheckBox = qt["QCheckBox"]
        QTimer = qt["QTimer"]

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Calibration / Diagnostics Lab")
                self._cfg = cfg
                self._status = runtime_status
                self._sender = calibration_sender
                self._step = 0
                self._elapsed_ms = 0
                self._auto_timer = QTimer(self)
                self._auto_timer.timeout.connect(self._on_auto_step_tick)

                self.mode_combo = QComboBox()
                self.mode_combo.addItems(["coverage sanity", "direction walk", "corner anchors", "fine offset"])
                self.zone_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_slider.setRange(1, 128)
                initial_zone_count = int(
                    cfg.device_zone_count
                    or runtime_status.get("device_zone_count")
                    or (len(cfg.zones) if cfg.zones else 0)
                    or 8
                )
                self.zone_slider.setValue(max(1, initial_zone_count))
                self.zone_value = QLabel("")
                self.duration_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.duration_slider.setRange(1, 60)
                self.duration_slider.setValue(15)
                self.duration_value = QLabel("")
                self.interval_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.interval_slider.setRange(100, 2000)
                self.interval_slider.setValue(400)
                self.interval_value = QLabel("")
                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.brightness_slider.setRange(5, 100)
                self.brightness_slider.setValue(int(cfg.brightness * 100))
                self.brightness_value = QLabel("")
                self.loop_checkbox = QCheckBox("Loop")
                self.loop_checkbox.setChecked(True)
                self.auto_step_checkbox = QCheckBox("Auto-step")
                self.off_except_active_checkbox = QCheckBox("All off except active zone")
                self.off_except_active_checkbox.setChecked(True)

                self.prev_button = QPushButton("Previous zone")
                self.next_button = QPushButton("Next zone")
                self.send_button = QPushButton("Send now")

                self.status_label = QLabel("")
                self.debug_label = QLabel("")
                self.sequence_label = QLabel(calibration_sequence_text())
                self.test_label = QLabel("")

                self.prev_button.clicked.connect(self._prev)
                self.next_button.clicked.connect(self._next)
                self.send_button.clicked.connect(self._send)
                self.mode_combo.currentIndexChanged.connect(self._refresh)
                self.zone_slider.valueChanged.connect(self._refresh)
                self.duration_slider.valueChanged.connect(self._refresh)
                self.interval_slider.valueChanged.connect(self._refresh)
                self.brightness_slider.valueChanged.connect(self._refresh)
                self.interval_slider.valueChanged.connect(self._on_interval_changed)
                self.auto_step_checkbox.stateChanged.connect(self._on_auto_step_toggled)

                layout = QGridLayout()
                layout.addWidget(QLabel("Backend selection"), 0, 0, 1, 3)
                layout.addWidget(self.status_label, 1, 0, 1, 3)
                layout.addWidget(self.debug_label, 2, 0, 1, 3)
                layout.addWidget(QLabel("Calibration sequence"), 3, 0, 1, 3)
                layout.addWidget(self.sequence_label, 4, 0, 1, 3)
                layout.addWidget(QLabel("Test mode"), 5, 0)
                layout.addWidget(self.mode_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Device zone count used for test"), 6, 0)
                layout.addWidget(self.zone_slider, 6, 1)
                layout.addWidget(self.zone_value, 6, 2)
                layout.addWidget(QLabel("Test duration (s)"), 7, 0)
                layout.addWidget(self.duration_slider, 7, 1)
                layout.addWidget(self.duration_value, 7, 2)
                layout.addWidget(QLabel("Step interval (ms)"), 8, 0)
                layout.addWidget(self.interval_slider, 8, 1)
                layout.addWidget(self.interval_value, 8, 2)
                layout.addWidget(QLabel("Test brightness"), 9, 0)
                layout.addWidget(self.brightness_slider, 9, 1)
                layout.addWidget(self.brightness_value, 9, 2)
                layout.addWidget(self.loop_checkbox, 10, 0, 1, 2)
                layout.addWidget(self.auto_step_checkbox, 11, 0, 1, 2)
                layout.addWidget(self.off_except_active_checkbox, 12, 0, 1, 2)
                layout.addWidget(self.prev_button, 13, 0)
                layout.addWidget(self.next_button, 13, 1)
                layout.addWidget(self.send_button, 13, 2)
                layout.addWidget(self.test_label, 14, 0, 1, 3)
                self.setLayout(layout)
                self._refresh()

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

            def _effective_zone_count(self) -> int:
                return int(self.zone_slider.value())

            def _current_step(self):
                mode = str(self.mode_combo.currentText())
                count = self._effective_zone_count()
                source_zone_count = max(1, len(self._cfg.zones) if self._cfg.zones else count)
                if mode == "corner anchors":
                    anchors = corner_anchor_steps(
                        zone_count=source_zone_count,
                        device_zone_count=count,
                        zone_offset=int(self._cfg.zone_offset),
                        reverse_zones=bool(self._cfg.reverse_zones),
                        explicit_zone_map=self._cfg.explicit_zone_map,
                    )
                    return anchors[self._step % len(anchors)]
                if mode == "coverage sanity":
                    return coverage_sanity_step(
                        step=self._step,
                        zone_count=source_zone_count,
                        device_zone_count=count,
                        zone_offset=int(self._cfg.zone_offset),
                        reverse_zones=bool(self._cfg.reverse_zones),
                        explicit_zone_map=self._cfg.explicit_zone_map,
                    )
                return single_zone_step(
                    step=self._step,
                    zone_count=source_zone_count,
                    device_zone_count=count,
                    zone_offset=int(self._cfg.zone_offset),
                    reverse_zones=bool(self._cfg.reverse_zones),
                    explicit_zone_map=self._cfg.explicit_zone_map,
                    label_prefix="Direction walk" if mode == "direction walk" else "Fine offset",
                )

            def _refresh(self) -> None:
                snapshot = self._snapshot()
                self.status_label.setText(
                    f"Requested backend: {snapshot.requested_backend} | Effective: {snapshot.effective_backend} | "
                    f"Reason: {snapshot.selection_reason}"
                )
                self.debug_label.setText(
                    f"From auto probe: {snapshot.from_auto_probe} | Auto probe timestamp: {snapshot.auto_probe_timestamp} | "
                    f"Detected strip zones: {snapshot.detected_device_zone_count or 'unknown'} | "
                    f"Configured strip zones: {snapshot.configured_device_zone_count or 'auto'}"
                )
                self.zone_value.setText(str(self.zone_slider.value()))
                self.duration_value.setText(str(self.duration_slider.value()))
                self.interval_value.setText(str(self.interval_slider.value()))
                self.brightness_value.setText(f"{self.brightness_slider.value()}%")
                self.test_label.setText(self._current_step().label)

            def _send(self) -> None:
                if self._sender is None:
                    return
                step = self._current_step()
                inactive_color = (0, 0, 0) if self.off_except_active_checkbox.isChecked() else (8, 8, 8)
                self._sender(
                    calibration_test_frame(
                        device_zone_count=self._effective_zone_count(),
                        active_indices=[step.device_zone_index],
                        inactive_color=inactive_color,
                        brightness=self.brightness_slider.value() / 100.0,
                    )
                )

            def _next(self) -> None:
                self._step += 1
                self._refresh()
                self._send()

            def _prev(self) -> None:
                self._step -= 1
                self._refresh()
                self._send()

            def _on_interval_changed(self) -> None:
                if self._auto_timer.isActive():
                    self._auto_timer.setInterval(max(100, int(self.interval_slider.value())))

            def _on_auto_step_toggled(self) -> None:
                self._elapsed_ms = 0
                if self.auto_step_checkbox.isChecked():
                    self._auto_timer.start(max(100, int(self.interval_slider.value())))
                else:
                    self._auto_timer.stop()

            def _on_auto_step_tick(self) -> None:
                self._elapsed_ms += max(100, int(self.interval_slider.value()))
                duration_ms = int(self.duration_slider.value()) * 1000
                if self._elapsed_ms >= duration_ms:
                    if self.loop_checkbox.isChecked():
                        self._elapsed_ms = 0
                        self._step = 0
                    else:
                        self.auto_step_checkbox.setChecked(False)
                        self._auto_timer.stop()
                        return
                self._next()

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def show(self) -> None:
        self._dialog.show()

    def raise_(self) -> None:
        self._dialog.raise_()

    def activateWindow(self) -> None:
        self._dialog.activateWindow()

    def set_runtime_status(self, runtime_status: dict) -> None:
        self._dialog._status = runtime_status
        self._dialog._refresh()
