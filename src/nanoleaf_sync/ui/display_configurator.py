from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Callable

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    build_testing_panel_state,
)
from nanoleaf_sync.ui.calibration_widget import SimpleCalibrationWidget
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_calibration import corner_anchor_validation_summary
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

MAX_WIZARD_ZONE_COUNT = 128
WIZARD_STEPS: tuple[str, ...] = (
    "Calibration",
    "Display Preset",
    "Look & Feel",
)
CALIBRATION_MODE_CORNER = "corner+offset alignment"
_log = logging.getLogger(__name__)
WIZARD_SESSION_ENV = "NANOLEAF_WIZARD_SESSION_PATH"


def _wizard_session_storage_path() -> Path:
    configured = os.environ.get(WIZARD_SESSION_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "nanoleaf-sync" / "wizard-session.json"


def _should_prefer_detected_zone_count(*, cfg: AppConfig, detected_device_zone_count: int) -> bool:
    detected = int(detected_device_zone_count or 0)
    if detected <= 0:
        return False
    configured = int(getattr(cfg, "device_zone_count", 0) or 0)
    nested = int(getattr(getattr(cfg, "calibration", None), "device_zone_count", 0) or 0)
    if configured <= 0:
        return True
    if configured == detected:
        return False
    # Legacy first-run defaults may persist a stale value of 8 while runtime/device
    # discovery reports the actual strip length. Treat this as auto-detected unless
    # setup has already been explicitly completed by the user.
    return (
        not bool(getattr(cfg, "wizard_completed", False))
        and configured == 8
        and nested in {0, 8}
    )

class _FallbackStackedWidget:
    def __init__(self) -> None:
        self._index = 0

    def addWidget(self, *_args, **_kwargs) -> None:
        return None

    def setCurrentIndex(self, index: int) -> None:
        self._index = index


class _FallbackLayout:
    def addWidget(self, *_args, **_kwargs) -> None:
        return None

    def addLayout(self, *_args, **_kwargs) -> None:
        return None


class _FallbackWidget:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def setLayout(self, *_args, **_kwargs) -> None:
        return None


class _FallbackGroupBox(_FallbackWidget):
    def setCheckable(self, *_args, **_kwargs) -> None:
        return None

    def setChecked(self, *_args, **_kwargs) -> None:
        return None


def _qt_widget(qt: dict[str, object], name: str, fallback):
    return qt.get(name, fallback)


def _set_checkable(widget, value: bool) -> None:
    setter = getattr(widget, "setCheckable", None)
    if callable(setter):
        setter(value)


def _set_checked(widget, value: bool) -> None:
    setter = getattr(widget, "setChecked", None)
    if callable(setter):
        setter(value)


@dataclass
class WizardFlowState:
    total_steps: int = len(WIZARD_STEPS)
    index: int = 0
    step_validity: dict[int, bool] = field(default_factory=dict)

    def can_go_back(self) -> bool:
        return self.index > 0

    def can_go_next(self) -> bool:
        return self.index < (self.total_steps - 1) and self.step_validity.get(self.index, True)

    def step_label(self) -> str:
        return f"Step {self.index + 1}/{self.total_steps}: {WIZARD_STEPS[self.index]}"

    def next(self) -> None:
        if self.can_go_next():
            self.index += 1

    def back(self) -> None:
        if self.can_go_back():
            self.index -= 1

    def set_step_valid(self, step_index: int, valid: bool) -> None:
        self.step_validity[int(step_index)] = bool(valid)


class DisplayConfiguratorDialog:
    """First-run step-by-step display setup wizard."""

    def __init__(
        self,
        parent,
        cfg: AppConfig,
        *,
        calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None,
        runtime_status: dict | None = None,
    ):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QLabel = qt["QLabel"]
        QVBoxLayout = qt["QVBoxLayout"]
        QGridLayout = qt["QGridLayout"]
        QComboBox = qt["QComboBox"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]
        QTimer = _qt_widget(qt, "QTimer", None)
        QGroupBox = _qt_widget(qt, "QGroupBox", _FallbackGroupBox)
        QStackedWidget = _qt_widget(qt, "QStackedWidget", _FallbackStackedWidget)
        QWidget = _qt_widget(qt, "QWidget", _FallbackWidget)
        QHBoxLayout = _qt_widget(qt, "QHBoxLayout", _FallbackLayout)

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Setup Wizard")
                resize = getattr(self, "resize", None)
                if callable(resize):
                    resize(700, 440)
                self._calibration_sender = calibration_sender
                self._test_step = 0
                self._state = CalibrationState.from_config(cfg)
                self._flow = WizardFlowState()
                self._initial_calibration = cfg.effective_calibration()
                status = runtime_status or {}
                detected_device_zone_count = int(status.get("device_zone_count") or 0)
                should_prefer_detected = _should_prefer_detected_zone_count(
                    cfg=cfg,
                    detected_device_zone_count=detected_device_zone_count,
                )
                self._requires_manual_device_zone_count = (
                    int(getattr(cfg, "device_zone_count", 0)) <= 0
                    and detected_device_zone_count <= 0
                )
                self._device_zone_count_confirmed = not self._requires_manual_device_zone_count
                if should_prefer_detected:
                    self._state.device_zone_count = detected_device_zone_count

                self.step_label = QLabel("")
                self._preview_phase = 0
                self._suspend_session_persist = True
                self._first_run_defaults = not bool(getattr(cfg, "wizard_completed", False))
                self._live_preview_timer = QTimer(self) if callable(QTimer) else None
                self._last_preview_refresh_ms = 0.0

                # Step 2
                self.display_mode_combo = QComboBox()
                self.display_mode_combo.addItems(["sdr", "hdr"])
                self.display_mode_combo.setCurrentIndex(self.display_mode_combo.findText("hdr" if cfg.hdr_enabled else "sdr"))
                self.preset_sdr_button = QPushButton("SDR preset")
                self.preset_hdr_button = QPushButton("HDR preset")
                _set_checkable(self.preset_sdr_button, True)
                _set_checkable(self.preset_hdr_button, True)
                self.preset_sdr_help = QLabel("Low-maintenance SDR-safe path.")
                self.preset_hdr_help = QLabel("HDR-first with wide-gamut defaults.")

                # Step 3
                self.color_mode_combo = QComboBox()
                allowed_color_modes = ["balanced", "dynamic"]
                current_color_mode = str(getattr(cfg, "color_mode", "balanced"))
                if current_color_mode not in allowed_color_modes:
                    allowed_color_modes.append(current_color_mode)
                self.color_mode_combo.addItems(allowed_color_modes)
                self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(current_color_mode)))
                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq"])
                self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))))
                self.hdr_transfer_label = QLabel("HDR transfer")
                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))))
                self.hdr_primaries_label = QLabel("HDR primaries")
                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(80, 10000)
                self.hdr_max_nits_slider.setValue(min(int(getattr(cfg, "hdr_max_nits", 1000.0)), self.hdr_max_nits_slider.maximum()))
                self.hdr_max_nits_label = QLabel("HDR max brightness")
                self.hdr_max_nits_value = QLabel("")
                self.vibrancy_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.vibrancy_slider.setRange(100, 400)
                self.vibrancy_slider.setValue(int(round(float(getattr(cfg, "led_gamma", 1.0)) * 100)))
                self.vibrancy_value = QLabel("")
                self.sampling_low_button = QPushButton("Low quality")
                self.sampling_balanced_button = QPushButton("Balanced quality")
                self.sampling_high_button = QPushButton("High quality")
                self.dynamism_balanced_button = QPushButton("Calm")
                self.dynamism_dynamic_button = QPushButton("Dynamic")
                for button in (
                    self.sampling_low_button,
                    self.sampling_balanced_button,
                    self.sampling_high_button,
                    self.dynamism_balanced_button,
                    self.dynamism_dynamic_button,
                ):
                    _set_checkable(button, True)

                # Shared controls
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, MAX_WIZARD_ZONE_COUNT)
                self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_count_value = QLabel("")
                self.sampling_quality_combo = QComboBox()
                self.sampling_quality_combo.addItems(["Low", "Balanced", "High"])
                self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(str(getattr(cfg, "sampling_quality", "balanced")).capitalize())))
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["Edge strip (recommended)", "Full-screen horizontal"])
                self.zone_preset_combo.setCurrentIndex(0 if self._state.zone_preset == "edge-weighted" else 1)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, MAX_WIZARD_ZONE_COUNT)
                self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_value = QLabel("")
                self.device_zone_status = QLabel("")
                self.device_zone_summary = QLabel("")
                self.zone_count_explanation = QLabel("")
                self.zone_change_notice = QLabel("")

                # Step 1
                self.simple_calibration_widget = SimpleCalibrationWidget(qt=qt, title="Corner calibration")
                self.reverse_checkbox = self.simple_calibration_widget.reverse_orientation_checkbox
                self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                initial_offset_limit = max(1, self._state.effective_device_zone_count() - 1)
                self.zone_offset_slider.setRange(-initial_offset_limit, initial_offset_limit)
                self.zone_offset_slider.setValue(self._state.zone_offset)
                self.zone_offset_value = QLabel("")
                self.test_step_index_value = self.simple_calibration_widget.step_index_label
                self.preview_text = self.simple_calibration_widget.preview_text_label
                self.preview_visual = self.simple_calibration_widget.preview_visual_label
                self.calibration_test_label = QLabel("")
                self.anchor_validation_label = QLabel("")
                self.calibration_next_button = self.simple_calibration_widget.next_zone_button
                self.calibration_prev_button = self.simple_calibration_widget.prev_zone_button
                self.calibration_send_button = QPushButton("Send test pattern")
                self.assign_tl_button = self.simple_calibration_widget.assign_top_left_button
                self.assign_tr_button = self.simple_calibration_widget.assign_top_right_button
                self.assign_br_button = self.simple_calibration_widget.assign_bottom_right_button
                self.assign_bl_button = self.simple_calibration_widget.assign_bottom_left_button
                self.reset_anchors_button = self.simple_calibration_widget.reset_anchors_button
                self.current_zone_label = self.simple_calibration_widget.current_zone_label
                self.calibration_hint = QLabel(
                    "Use Previous/Next zone to find the right physical LED, assign corners, and adjust reverse orientation/offset if needed."
                )

                # Summary
                self.summary_label = QLabel("")
                self.finish_policy_note = QLabel("")

                self.cancel_button = QPushButton("Cancel")
                self.back_button = QPushButton("Back")
                self.next_button = QPushButton("Next")
                self.finish_button = QPushButton("Finish")
                self.cancel_button.clicked.connect(self._cancel)
                self.back_button.clicked.connect(self._go_back)
                self.next_button.clicked.connect(self._go_next)
                self.finish_button.clicked.connect(self._finish)
                if self._live_preview_timer is not None:
                    self._live_preview_timer.setInterval(350)
                    self._live_preview_timer.timeout.connect(self._send_live_preview)

                for signal in (
                    self.display_mode_combo.currentIndexChanged,
                    self.zone_count_slider.valueChanged,
                    self.sampling_quality_combo.currentIndexChanged,
                    self.color_mode_combo.currentIndexChanged,
                    self.vibrancy_slider.valueChanged,
                    self.zone_offset_slider.valueChanged,
                    self.zone_preset_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                ):
                    signal.connect(self._refresh)
                self.preset_sdr_button.clicked.connect(lambda: self._apply_display_preset("sdr"))
                self.preset_hdr_button.clicked.connect(lambda: self._apply_display_preset("hdr"))
                self.sampling_low_button.clicked.connect(lambda: self._set_sampling_preset("low"))
                self.sampling_balanced_button.clicked.connect(lambda: self._set_sampling_preset("balanced"))
                self.sampling_high_button.clicked.connect(lambda: self._set_sampling_preset("high"))
                self.dynamism_balanced_button.clicked.connect(lambda: self._set_dynamism_preset("balanced"))
                self.dynamism_dynamic_button.clicked.connect(lambda: self._set_dynamism_preset("dynamic"))
                self.device_zone_count_slider.valueChanged.connect(self._on_device_zone_count_changed)

                self.hdr_max_nits_slider.valueChanged.connect(self._refresh)
                self.simple_calibration_widget.bind_callbacks(
                    on_prev_zone=self._prev_test_zone,
                    on_next_zone=self._next_test_zone,
                    on_assign_top_left=lambda: self._assign_anchor("top_left"),
                    on_assign_top_right=lambda: self._assign_anchor("top_right"),
                    on_assign_bottom_right=lambda: self._assign_anchor("bottom_right"),
                    on_assign_bottom_left=lambda: self._assign_anchor("bottom_left"),
                    on_reset_anchors=self._reset_anchors,
                    on_reverse_orientation_changed=self._on_calibration_controls_changed,
                )
                self.calibration_send_button.clicked.connect(self._send_test_pattern)
                self.zone_offset_slider.valueChanged.connect(self._on_calibration_controls_changed)

                self.pages = QStackedWidget()
                self.pages.addWidget(self._build_step_1(QWidget, QGridLayout, QLabel))
                self.pages.addWidget(self._build_step_2(QWidget, QGridLayout, QLabel))
                self.pages.addWidget(self._build_step_3(QWidget, QGridLayout, QLabel))

                layout = QVBoxLayout()
                set_margins = getattr(layout, "setContentsMargins", None)
                if callable(set_margins):
                    set_margins(12, 10, 12, 10)
                set_spacing = getattr(layout, "setSpacing", None)
                if callable(set_spacing):
                    set_spacing(8)
                layout.addWidget(self.step_label)
                layout.addWidget(self.pages)
                actions = QHBoxLayout()
                action_spacing = getattr(actions, "setSpacing", None)
                if callable(action_spacing):
                    action_spacing(6)
                actions.addWidget(self.cancel_button)
                actions.addWidget(self.back_button)
                actions.addWidget(self.next_button)
                actions.addWidget(self.finish_button)
                layout.addLayout(actions)
                self.setLayout(layout)

                self._refresh()
                self._configure_tooltips()
                self._restore_wizard_draft()
                self._restore_wizard_session()
                self._suspend_session_persist = False
                self._save_wizard_session()

            def _set_tooltip(self, widget, text: str) -> None:
                setter = getattr(widget, "setToolTip", None)
                if callable(setter):
                    setter(text)

            def _configure_tooltips(self) -> None:
                self._set_tooltip(self.zone_offset_slider, "Global mapping zone offset that shifts the strip mapping ring by whole zones.")
                self._set_tooltip(self.reverse_checkbox, "Flip mapping direction if strip order is reversed.")
                self._set_tooltip(self.calibration_send_button, "Send a fresh calibration frame to the strip right now.")
                self._set_tooltip(self.calibration_next_button, "Move to the next test zone step and transmit it.")
                self._set_tooltip(self.calibration_prev_button, "Move to the previous test zone step and transmit it.")
                self._set_tooltip(self.assign_tl_button, "Assign the currently lit strip zone as top-left screen corner.")
                self._set_tooltip(self.assign_tr_button, "Assign the currently lit strip zone as top-right screen corner.")
                self._set_tooltip(self.assign_br_button, "Assign the currently lit strip zone as bottom-right screen corner.")
                self._set_tooltip(self.assign_bl_button, "Assign the currently lit strip zone as bottom-left screen corner.")
                self._set_tooltip(self.reset_anchors_button, "Clear all corner assignments and start anchor placement again.")
                self._set_tooltip(self.preset_sdr_button, "SDR-safe defaults: srgb + bt709.")
                self._set_tooltip(self.preset_hdr_button, "HDR defaults: pq + bt2020.")
                self._set_tooltip(self.sampling_low_button, "Fastest response, lowest CPU usage.")
                self._set_tooltip(self.sampling_balanced_button, "Recommended default quality.")
                self._set_tooltip(self.sampling_high_button, "Highest fidelity at higher CPU cost.")
                self._set_tooltip(self.dynamism_balanced_button, "Stable color behavior with less motion punch.")
                self._set_tooltip(self.dynamism_dynamic_button, "Stronger motion-reactive color changes.")

            def _build_step_1(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Calibration and testing"), 0, 0, 1, 3)
                layout.addWidget(self.calibration_hint, 1, 0, 1, 3)
                layout.addWidget(QLabel("Strip LED zone count"), 2, 0)
                layout.addWidget(self.device_zone_count_slider, 2, 1)
                layout.addWidget(self.device_zone_count_value, 2, 2)
                layout.addWidget(self.device_zone_status, 3, 0, 1, 3)
                layout.addWidget(self.zone_change_notice, 4, 0, 1, 3)
                row = self.simple_calibration_widget.add_to_layout(layout, row=5, include_header=False)
                layout.addWidget(self.calibration_send_button, row, 0, 1, 3); row += 1
                layout.addWidget(QLabel("Global mapping zone offset"), row, 0)
                layout.addWidget(self.zone_offset_slider, row, 1)
                layout.addWidget(self.zone_offset_value, row, 2); row += 1
                layout.addWidget(self.anchor_validation_label, row, 0, 1, 3)
                page.setLayout(layout)
                return page

            def _build_step_2(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Pick a display preset"), 0, 0, 1, 3)
                layout.addWidget(self.preset_sdr_button, 1, 0, 1, 3)
                layout.addWidget(self.preset_sdr_help, 2, 0, 1, 3)
                layout.addWidget(self.preset_hdr_button, 3, 0, 1, 3)
                layout.addWidget(self.preset_hdr_help, 4, 0, 1, 3)
                layout.addWidget(self.hdr_transfer_label, 5, 0)
                layout.addWidget(self.hdr_transfer_combo, 5, 1, 1, 2)
                layout.addWidget(self.hdr_primaries_label, 6, 0)
                layout.addWidget(self.hdr_primaries_combo, 6, 1, 1, 2)
                layout.addWidget(self.hdr_max_nits_label, 7, 0)
                layout.addWidget(self.hdr_max_nits_slider, 7, 1)
                layout.addWidget(self.hdr_max_nits_value, 7, 2)
                page.setLayout(layout)
                return page

            def _build_step_3(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Tune visual style with live preview"), 0, 0, 1, 3)
                layout.addWidget(self.sampling_low_button, 1, 0)
                layout.addWidget(self.sampling_balanced_button, 1, 1)
                layout.addWidget(self.sampling_high_button, 1, 2)
                layout.addWidget(self.dynamism_balanced_button, 2, 0, 1, 2)
                layout.addWidget(self.dynamism_dynamic_button, 2, 2)
                layout.addWidget(QLabel("Optional vibrancy"), 3, 0)
                layout.addWidget(self.vibrancy_slider, 3, 1)
                layout.addWidget(self.vibrancy_value, 3, 2)
                layout.addWidget(QLabel("Screen sampling zone count"), 4, 0)
                layout.addWidget(self.zone_count_slider, 4, 1)
                layout.addWidget(self.zone_count_value, 4, 2)
                layout.addWidget(QLabel("Zone layout preset"), 5, 0)
                layout.addWidget(self.zone_preset_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Strip LED zone count"), 6, 0)
                layout.addWidget(self.device_zone_summary, 6, 1, 1, 2)
                layout.addWidget(self.zone_count_explanation, 7, 0, 1, 3)
                layout.addWidget(self.summary_label, 8, 0, 1, 3)
                layout.addWidget(self.finish_policy_note, 9, 0, 1, 3)
                page.setLayout(layout)
                return page

            def _apply_display_preset(self, preset: str) -> None:
                index = self.display_mode_combo.findText(str(preset))
                if index >= 0:
                    self.display_mode_combo.setCurrentIndex(index)
                if str(preset) == "hdr":
                    self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText("pq")))
                    self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText("bt2020")))
                else:
                    self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText("srgb")))
                    self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText("bt709")))
                self._refresh()

            def _cancel(self) -> None:
                self.reject()

            def _finish(self) -> None:
                self._clear_wizard_session()
                self.accept()

            def reject(self) -> None:  # type: ignore[override]
                self._stop_live_preview()
                super().reject()

            def accept(self) -> None:  # type: ignore[override]
                self._stop_live_preview()
                super().accept()

            def _set_sampling_preset(self, preset: str) -> None:
                self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(str(preset).capitalize())))
                self._refresh()

            def _set_dynamism_preset(self, preset: str) -> None:
                self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(str(preset))))
                self._refresh()

            def _go_next(self) -> None:
                previous_step = self._flow.index
                self._flow.next()
                if previous_step == 0 and self._flow.index == 1:
                    self._send_live_preview()
                    self._ensure_live_preview_running()
                self._refresh()

            def _go_back(self) -> None:
                self._flow.back()
                if self._flow.index == 0:
                    self._stop_live_preview()
                self._refresh()

            def _pull_state_from_controls(self) -> None:
                self._state.zone_count = int(self.zone_count_slider.value())
                self._state.zone_preset = "edge-weighted" if str(self.zone_preset_combo.currentText()).startswith("Edge strip") else "horizontal"
                self._state.zone_offset = int(self.zone_offset_slider.value())
                self._state.reverse_zones = bool(self.reverse_checkbox.isChecked())
                self._state.device_zone_count = int(self.device_zone_count_slider.value())
                self._state.corner_offsets_enabled = False
                self._state.corner_zone_offsets = [0, 0, 0, 0]
                self._state.calibration_model = "corner_anchored"

            def _normalize_offset_for_count(self, offset: int, zone_count: int) -> int:
                total = max(1, int(zone_count))
                normalized = int(offset) % total
                half_turn = total // 2
                if normalized > half_turn:
                    normalized -= total
                return normalized

            def _remap_offset_between_counts(self, offset: int, previous_count: int, new_count: int) -> int:
                previous_total = max(1, int(previous_count))
                new_total = max(1, int(new_count))
                # Preserve rotational position on the ring; signed offset may change after
                # normalization when the strip LED zone count changes.
                preserved_position = int(offset) % previous_total
                return self._normalize_offset_for_count(preserved_position, new_total)

            def _remap_zone_index_between_counts(self, zone_index: int, previous_count: int, new_count: int) -> int:
                if int(zone_index) < 0:
                    return -1
                previous_total = max(1, int(previous_count))
                new_total = max(1, int(new_count))
                scaled = int(round((int(zone_index) / previous_total) * new_total)) % new_total
                return scaled

            def _calibration_offset_limit(self, zone_count: int) -> int:
                return max(1, int(zone_count) - 1)

            def _set_slider_value_safely(self, slider, value: int) -> None:
                if int(slider.value()) == int(value):
                    return
                block_signals = getattr(slider, "blockSignals", None)
                previous = False
                if callable(block_signals):
                    previous = bool(block_signals(True))
                slider.setValue(int(value))
                if callable(block_signals):
                    block_signals(previous)

            def _set_checkbox_value_safely(self, checkbox, value: bool) -> None:
                if bool(checkbox.isChecked()) == bool(value):
                    return
                block_signals = getattr(checkbox, "blockSignals", None)
                previous = False
                if callable(block_signals):
                    previous = bool(block_signals(True))
                checkbox.setChecked(bool(value))
                if callable(block_signals):
                    block_signals(previous)

            def _sync_zone_offset_slider(self, *, previous_zone_count: int | None = None) -> None:
                current_device_zone_count = max(1, int(self.device_zone_count_slider.value()))
                old_count = max(1, int(previous_zone_count or current_device_zone_count))
                remapped_offset = self._remap_offset_between_counts(
                    int(self.zone_offset_slider.value()),
                    old_count,
                    current_device_zone_count,
                )
                offset_limit = self._calibration_offset_limit(current_device_zone_count)
                self.zone_offset_slider.setRange(-offset_limit, offset_limit)
                self._set_slider_value_safely(self.zone_offset_slider, remapped_offset)

            def _active_calibration_step(self):
                step_total = self._state.cycle_length(CALIBRATION_MODE_CORNER)
                self._test_step %= step_total
                return self._state.step_for_mode(CALIBRATION_MODE_CORNER, self._test_step)

            def _current_calibration_mode(self) -> str:
                return CALIBRATION_MODE_CORNER

            def _on_device_zone_count_changed(self, *_args) -> None:
                previous_zone_count = self._state.effective_device_zone_count()
                self._device_zone_count_confirmed = True
                self._sync_zone_offset_slider(previous_zone_count=previous_zone_count)
                new_zone_count = max(1, int(self.device_zone_count_slider.value()))
                remapped = {
                    "top_left": self._remap_zone_index_between_counts(self._state.corner_anchor_top_left, previous_zone_count, new_zone_count),
                    "top_right": self._remap_zone_index_between_counts(self._state.corner_anchor_top_right, previous_zone_count, new_zone_count),
                    "bottom_right": self._remap_zone_index_between_counts(self._state.corner_anchor_bottom_right, previous_zone_count, new_zone_count),
                    "bottom_left": self._remap_zone_index_between_counts(self._state.corner_anchor_bottom_left, previous_zone_count, new_zone_count),
                }
                self._state.corner_anchor_top_left = remapped["top_left"]
                self._state.corner_anchor_top_right = remapped["top_right"]
                self._state.corner_anchor_bottom_right = remapped["bottom_right"]
                self._state.corner_anchor_bottom_left = remapped["bottom_left"]
                if previous_zone_count != new_zone_count:
                    self._test_step = 0
                    self.zone_change_notice.setText(
                        "Strip zone count changed: remapped offset/corner anchors and reset calibration test step to 1."
                    )
                self._refresh()

            def _refresh(self) -> None:
                refresh_started = perf_counter()
                self._pull_state_from_controls()
                if not bool(self._suspend_session_persist):
                    self._save_wizard_session()
                self.pages.setCurrentIndex(self._flow.index)
                self.step_label.setText(self._flow.step_label())
                _set_checked(self.preset_sdr_button, str(self.display_mode_combo.currentText()) == "sdr")
                _set_checked(self.preset_hdr_button, str(self.display_mode_combo.currentText()) == "hdr")
                sampling_choice = str(self.sampling_quality_combo.currentText()).lower()
                _set_checked(self.sampling_low_button, sampling_choice == "low")
                _set_checked(self.sampling_balanced_button, sampling_choice == "balanced")
                _set_checked(self.sampling_high_button, sampling_choice == "high")
                mode_choice = str(self.color_mode_combo.currentText())
                _set_checked(self.dynamism_balanced_button, mode_choice == "balanced")
                _set_checked(self.dynamism_dynamic_button, mode_choice == "dynamic")
                back_set_enabled = getattr(self.back_button, "setEnabled", None)
                if callable(back_set_enabled):
                    back_set_enabled(self._flow.can_go_back())
                next_set_enabled = getattr(self.next_button, "setEnabled", None)
                if callable(next_set_enabled):
                    next_set_enabled(self._flow.can_go_next())
                effective_zone_count = self._state.effective_device_zone_count()
                corner_mode = True
                mapping_snapshot = self._state.resolved_mapping_snapshot()
                anchors = {
                    "top_left": self._state.corner_anchor_top_left if self._state.corner_anchor_top_left >= 0 else None,
                    "top_right": self._state.corner_anchor_top_right if self._state.corner_anchor_top_right >= 0 else None,
                    "bottom_right": self._state.corner_anchor_bottom_right if self._state.corner_anchor_bottom_right >= 0 else None,
                    "bottom_left": self._state.corner_anchor_bottom_left if self._state.corner_anchor_bottom_left >= 0 else None,
                }
                anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=effective_zone_count)
                invalid_anchor_fallback = corner_mode and mapping_snapshot.invalid_corner_anchor_fallback_active
                for widget in (
                    self.assign_tl_button,
                    self.assign_tr_button,
                    self.assign_br_button,
                    self.assign_bl_button,
                    self.anchor_validation_label,
                ):
                    set_visible = getattr(widget, "setVisible", None)
                    if callable(set_visible):
                        set_visible(corner_mode)
                    set_enabled = getattr(widget, "setEnabled", None)
                    if callable(set_enabled) and widget is not self.anchor_validation_label:
                        set_enabled(corner_mode)
                self.anchor_validation_label.setText(
                    ""
                    if not corner_mode
                    else (
                        "Corner anchors complete.\n"
                        + corner_anchor_validation_summary(
                            device_zone_count=effective_zone_count,
                            corner_anchor_top_left=self._state.corner_anchor_top_left,
                            corner_anchor_top_right=self._state.corner_anchor_top_right,
                            corner_anchor_bottom_right=self._state.corner_anchor_bottom_right,
                            corner_anchor_bottom_left=self._state.corner_anchor_bottom_left,
                        )
                        if anchor_validation.valid
                        else "Anchor validation error: "
                        + " ".join(anchor_validation.errors)
                        + (
                            ""
                            if not invalid_anchor_fallback
                            else (
                                f"\nAlignment warnings: [{', '.join(mapping_snapshot.warning_codes) if mapping_snapshot.warning_codes else 'none'}]"
                            )
                        )
                        + "\n"
                        + corner_anchor_validation_summary(
                            device_zone_count=effective_zone_count,
                            corner_anchor_top_left=self._state.corner_anchor_top_left,
                            corner_anchor_top_right=self._state.corner_anchor_top_right,
                            corner_anchor_bottom_right=self._state.corner_anchor_bottom_right,
                            corner_anchor_bottom_left=self._state.corner_anchor_bottom_left,
                        )
                    )
                )

                verification = self._state.validation_report()
                calibration_step_valid = self._device_zone_count_confirmed and anchor_validation.valid and not invalid_anchor_fallback
                self._flow.set_step_valid(0, calibration_step_valid)
                self._flow.set_step_valid(1, True)
                self._flow.set_step_valid(2, True)
                if callable(next_set_enabled):
                    next_set_enabled(self._flow.can_go_next())

                finish_set_enabled = getattr(self.finish_button, "setEnabled", None)
                can_finish = (
                    not self._flow.can_go_next()
                    and self._device_zone_count_confirmed
                    and anchor_validation.valid
                    and not invalid_anchor_fallback
                    and not verification.hard_fail
                )
                if callable(finish_set_enabled):
                    finish_set_enabled(can_finish)
                self.finish_policy_note.setText(
                    "Finish unlocks after valid corner anchors are assigned and strip zone count is confirmed."
                )

                hdr_mode = str(self.display_mode_combo.currentText()) == "hdr"
                for widget in (
                    self.hdr_transfer_label,
                    self.hdr_transfer_combo,
                    self.hdr_primaries_label,
                    self.hdr_primaries_combo,
                    self.hdr_max_nits_label,
                    self.hdr_max_nits_slider,
                    self.hdr_max_nits_value,
                ):
                    widget.setVisible(hdr_mode)

                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.vibrancy_value.setText(f"{self.vibrancy_slider.value()}%")
                normalized_offset = self._normalize_offset_for_count(
                    int(self.zone_offset_slider.value()),
                    effective_zone_count,
                )
                self.zone_offset_value.setText(
                    f"{normalized_offset:+d} (raw {int(self.zone_offset_slider.value()):+d})"
                )
                self.device_zone_count_value.setText(str(effective_zone_count))
                self.zone_count_explanation.setText(
                    "Screen sampling zones = sampled regions on your display. Strip LED zones = physical LEDs on the Nanoleaf strip."
                )
                if self._requires_manual_device_zone_count:
                    device_zone_status_text = (
                        f"Device metadata unavailable: manually set strip LED zone count (currently {effective_zone_count})."
                    )
                else:
                    device_zone_status_text = (
                        f"Strip LED zone count initialized from saved/device metadata (currently {effective_zone_count})."
                    )
                self.device_zone_status.setText(device_zone_status_text)
                self.device_zone_summary.setText(f"{effective_zone_count} physical strip LED zones")

                preview = build_testing_panel_state(
                    state=self._state,
                    runtime_status={},
                    cfg=cfg,
                    mode=self._current_calibration_mode(),
                    step=self._test_step,
                )
                self.preview_text.setText(self._state.mapping_preview_text())
                self.preview_visual.setText(self._state.mapping_preview_visual())
                self.calibration_test_label.setText(preview.active_test_description)
                active_step = self._active_calibration_step()
                current_zone = active_step.device_zone_index
                step_total = self._state.cycle_length(self._current_calibration_mode())
                self.simple_calibration_widget.set_step_status(
                    step_index=self._test_step,
                    step_total=step_total,
                    active_zone=current_zone,
                    normalized_offset=normalized_offset,
                )
                self.current_zone_label.setText(
                    f"Test zone step: {self._test_step + 1}/{step_total} | Active physical strip zone: {current_zone} | Normalized offset: {normalized_offset:+d}"
                )
                self.summary_label.setText(
                    "\n".join(
                        (
                            f"Display preset: {self.display_mode_combo.currentText().upper()}",
                            f"Dynamism: {self.color_mode_combo.currentText()}",
                            f"Zone preset: {self._state.zone_preset}",
                            f"Sampling quality: {self.sampling_quality_combo.currentText()}",
                            f"Vibrancy: {self.vibrancy_slider.value()}%",
                            f"Screen sampling zones: {self._state.zone_count}",
                            f"Effective strip LED zones: {effective_zone_count}",
                            f"Calibration model: {self._state.calibration_model}",
                            "Calibration mode: corner anchors",
                            (
                                "Verification: "
                                + verification.compact_summary()
                                + f" | Sentinel expected/assigned: {verification.expected_sentinels}/{verification.assigned_sentinels}"
                                + (
                                    ""
                                    if not verification.remediation_hints
                                    else f" | Remediation: {'; '.join(verification.remediation_hints)}"
                                )
                                + f" | Action: {verification.remediation_action}"
                            ),
                            device_zone_status_text,
                        )
                    )
                )
                self._last_preview_refresh_ms = (perf_counter() - refresh_started) * 1000.0
                if self._flow.index >= 1 and self._calibration_sender is not None:
                    self._ensure_live_preview_running()
                else:
                    self._stop_live_preview()

            def _on_calibration_controls_changed(self, *_args) -> None:
                if self._flow.index != 0:
                    return
                if self._calibration_sender is None:
                    return
                self._send_test_pattern()

            def updated_config(self) -> AppConfig:
                self._pull_state_from_controls()
                verification = self._state.validation_report()
                mapping_snapshot = resolve_calibration_mapping(
                    zone_count=max(1, int(self._state.zone_count)),
                    device_zone_count=max(1, int(self._state.effective_device_zone_count())),
                    zone_offset=int(self._state.zone_offset),
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    calibration_model="corner_anchored",
                )
                anchors = {
                    "top_left": self._state.corner_anchor_top_left if self._state.corner_anchor_top_left >= 0 else None,
                    "top_right": self._state.corner_anchor_top_right if self._state.corner_anchor_top_right >= 0 else None,
                    "bottom_right": self._state.corner_anchor_bottom_right if self._state.corner_anchor_bottom_right >= 0 else None,
                    "bottom_left": self._state.corner_anchor_bottom_left if self._state.corner_anchor_bottom_left >= 0 else None,
                }
                anchor_validation = validate_corner_anchors(
                    anchors=anchors,
                    device_zone_count=self._state.effective_device_zone_count(),
                )
                anchor_top_left = int(self._state.corner_anchor_top_left)
                anchor_top_right = int(self._state.corner_anchor_top_right)
                anchor_bottom_right = int(self._state.corner_anchor_bottom_right)
                anchor_bottom_left = int(self._state.corner_anchor_bottom_left)
                zone_count = self._state.zone_count
                new_zones = make_edge_weighted_zones(zone_count) if self._state.zone_preset == "edge-weighted" else make_horizontal_zones(zone_count)
                fallback_warning_codes = list(mapping_snapshot.warning_codes)
                fallback_strategy = str(mapping_snapshot.fallback_strategy or "")
                calibration_payload = CalibrationConfig(
                    schema_version=int(getattr(cfg, "calibration_schema_version", 1) or 1),
                    calibration_model="corner_anchored",
                    device_zone_count=int(self._state.device_zone_count),
                    output_channel_order=str(self._initial_calibration.output_channel_order),
                    zone_offset=int(self._state.zone_offset),
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
                    corner_anchor_top_left=anchor_top_left,
                    corner_anchor_top_right=anchor_top_right,
                    corner_anchor_bottom_right=anchor_bottom_right,
                    corner_anchor_bottom_left=anchor_bottom_left,
                    corner_anchor_fallback_active=bool(mapping_snapshot.invalid_corner_anchor_fallback_active),
                    corner_anchor_fallback_strategy=fallback_strategy,
                    corner_anchor_warning_codes=fallback_warning_codes,
                    corner_start_anchor=int(self._state.corner_start_anchor),
                    corner_offsets_enabled=bool(self._state.corner_offsets_enabled),
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                )
                return replace(
                    cfg,
                    hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    color_mode=str(self.color_mode_combo.currentText()),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    led_gamma=float(self.vibrancy_slider.value()) / 100.0,
                    zones=new_zones,
                    zone_preset=self._state.zone_preset,
                    sampling_quality=str(self.sampling_quality_combo.currentText()).lower(),
                    device_zone_count=self._state.device_zone_count,
                    reverse_zones=self._state.reverse_zones,
                    zone_offset=self._state.zone_offset,
                    corner_offsets_enabled=bool(self._state.corner_offsets_enabled),
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    corner_anchor_top_left=anchor_top_left,
                    corner_anchor_top_right=anchor_top_right,
                    corner_anchor_bottom_right=anchor_bottom_right,
                    corner_anchor_bottom_left=anchor_bottom_left,
                    corner_anchor_fallback_active=bool(mapping_snapshot.invalid_corner_anchor_fallback_active),
                    corner_anchor_fallback_strategy=fallback_strategy,
                    corner_anchor_warning_codes=fallback_warning_codes,
                    calibration_model="corner_anchored",
                    calibration_schema_version=int(calibration_payload.schema_version),
                    calibration=calibration_payload,
                    calibration_validation_confidence=float(verification.confidence_score),
                    calibration_validation_summary=(
                        verification.compact_summary()
                        + f" | sentinel_expected={verification.expected_sentinels} sentinel_assigned={verification.assigned_sentinels}"
                        + (
                            ""
                            if not verification.remediation_hints
                            else f" | Remediation: {'; '.join(verification.remediation_hints)}"
                        )
                        + f" | Action: {verification.remediation_action}"
                        + (
                            ""
                            if not mapping_snapshot.invalid_corner_anchor_fallback_active
                            else (
                                f" | fallback_strategy={fallback_strategy} "
                                f"fallback_warning_codes={tuple(fallback_warning_codes)}"
                            )
                        )
                    ),
                    wizard_in_progress_state="",
                    wizard_completed=True,
                )

            def _serialize_wizard_draft(self) -> str:
                self._pull_state_from_controls()
                mapping_snapshot = resolve_calibration_mapping(
                    zone_count=max(1, int(self._state.zone_count)),
                    device_zone_count=max(1, int(self._state.effective_device_zone_count())),
                    zone_offset=int(self._state.zone_offset),
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    calibration_model="corner_anchored",
                )
                payload = {
                    "flow_index": int(self._flow.index),
                    "test_step": int(self._test_step),
                    "zone_count": int(self._state.zone_count),
                    "zone_preset": str(self._state.zone_preset),
                    "zone_offset": int(self._state.zone_offset),
                    "reverse_zones": bool(self._state.reverse_zones),
                    "device_zone_count": int(self._state.device_zone_count),
                    "display_mode": str(self.display_mode_combo.currentText()),
                    "sampling_quality": str(self.sampling_quality_combo.currentText()).lower(),
                    "color_mode": str(self.color_mode_combo.currentText()),
                    "vibrancy": int(self.vibrancy_slider.value()),
                    "corner_anchor_top_left": int(self._state.corner_anchor_top_left),
                    "corner_anchor_top_right": int(self._state.corner_anchor_top_right),
                    "corner_anchor_bottom_right": int(self._state.corner_anchor_bottom_right),
                    "corner_anchor_bottom_left": int(self._state.corner_anchor_bottom_left),
                    "corner_anchor_fallback_active": bool(mapping_snapshot.invalid_corner_anchor_fallback_active),
                    "corner_anchor_fallback_strategy": str(mapping_snapshot.fallback_strategy or ""),
                    "corner_anchor_warning_codes": [str(code) for code in mapping_snapshot.warning_codes],
                }
                return json.dumps(payload, sort_keys=True)

            def in_progress_config(self) -> AppConfig:
                return replace(cfg, wizard_in_progress_state=self._serialize_wizard_draft())

            def _save_wizard_session(self) -> None:
                path = _wizard_session_storage_path()
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    payload = self._serialize_wizard_draft()
                    path.write_text(payload, encoding="utf-8")
                    try:
                        os.chmod(path, 0o600)
                    except Exception:
                        _log.debug("Could not set permissions on wizard session file", exc_info=True)
                except Exception:
                    _log.debug("Unable to persist wizard in-progress session state", exc_info=True)

            def _restore_wizard_session(self) -> None:
                path = _wizard_session_storage_path()
                if not path.exists():
                    return
                try:
                    raw = path.read_text(encoding="utf-8").strip()
                except Exception:
                    _log.debug("Unable to read wizard session state", exc_info=True)
                    return
                if not raw:
                    return
                restored = self._restore_wizard_state_payload(raw)
                if restored:
                    self.zone_change_notice.setText("Recovered unfinished calibration session from local draft storage.")

            def _clear_wizard_session(self) -> None:
                path = _wizard_session_storage_path()
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    _log.debug("Unable to clear wizard session state file", exc_info=True)

            def _restore_wizard_draft(self) -> None:
                raw = str(getattr(cfg, "wizard_in_progress_state", "") or "").strip()
                if not raw:
                    return
                self._restore_wizard_state_payload(raw)

            def _restore_wizard_state_payload(self, raw: str) -> bool:
                try:
                    data = json.loads(raw)
                except Exception:
                    return False
                if not isinstance(data, dict):
                    return False
                self._flow.index = max(0, min(len(WIZARD_STEPS) - 1, int(data.get("flow_index", self._flow.index))))
                self._test_step = int(data.get("test_step", self._test_step))
                self.zone_count_slider.setValue(int(data.get("zone_count", self.zone_count_slider.value())))
                preset = str(data.get("zone_preset", self._state.zone_preset))
                self.zone_preset_combo.setCurrentIndex(0 if preset == "edge-weighted" else 1)
                self.zone_offset_slider.setValue(int(data.get("zone_offset", self.zone_offset_slider.value())))
                self.reverse_checkbox.setChecked(bool(data.get("reverse_zones", self.reverse_checkbox.isChecked())))
                self.device_zone_count_slider.setValue(int(data.get("device_zone_count", self.device_zone_count_slider.value())))
                display_idx = self.display_mode_combo.findText(str(data.get("display_mode", self.display_mode_combo.currentText())))
                if display_idx >= 0:
                    self.display_mode_combo.setCurrentIndex(display_idx)
                sampling_idx = self.sampling_quality_combo.findText(str(data.get("sampling_quality", self.sampling_quality_combo.currentText())).capitalize())
                if sampling_idx >= 0:
                    self.sampling_quality_combo.setCurrentIndex(sampling_idx)
                color_idx = self.color_mode_combo.findText(str(data.get("color_mode", self.color_mode_combo.currentText())))
                if color_idx >= 0:
                    self.color_mode_combo.setCurrentIndex(color_idx)
                self.vibrancy_slider.setValue(int(data.get("vibrancy", self.vibrancy_slider.value())))
                self._state.corner_anchor_top_left = int(data.get("corner_anchor_top_left", self._state.corner_anchor_top_left))
                self._state.corner_anchor_top_right = int(data.get("corner_anchor_top_right", self._state.corner_anchor_top_right))
                self._state.corner_anchor_bottom_right = int(data.get("corner_anchor_bottom_right", self._state.corner_anchor_bottom_right))
                self._state.corner_anchor_bottom_left = int(data.get("corner_anchor_bottom_left", self._state.corner_anchor_bottom_left))
                self._refresh()
                return True

            def _assign_anchor(self, corner: str) -> None:
                self._pull_state_from_controls()
                current_zone = self._active_calibration_step().device_zone_index
                if corner == "top_left":
                    self._state.corner_anchor_top_left = current_zone
                elif corner == "top_right":
                    self._state.corner_anchor_top_right = current_zone
                elif corner == "bottom_right":
                    self._state.corner_anchor_bottom_right = current_zone
                elif corner == "bottom_left":
                    self._state.corner_anchor_bottom_left = current_zone
                # Re-resolve mapping immediately so preview and test frame use the latest anchors.
                self._state.resolved_mapping_snapshot()
                self._refresh()
                self._send_test_pattern()

            def _reset_anchors(self) -> None:
                self._pull_state_from_controls()
                self._state.corner_anchor_top_left = -1
                self._state.corner_anchor_top_right = -1
                self._state.corner_anchor_bottom_right = -1
                self._state.corner_anchor_bottom_left = -1
                self._state.resolved_mapping_snapshot()
                self._refresh()
                self._send_test_pattern()

            def _send_test_pattern(self) -> None:
                if self._calibration_sender is None:
                    return
                self._pull_state_from_controls()
                # Normalize self._test_step before generating the frame.
                self._active_calibration_step()
                mode = self._current_calibration_mode()
                off_frame = [(0, 0, 0)] * self._state.effective_device_zone_count()
                self._calibration_sender(off_frame)
                self._calibration_sender(
                    self._state.frame_for_step(
                        mode=mode,
                        step=self._test_step,
                        brightness=1.0,
                        all_off_except_active=True,
                    )
                )

            def _send_live_preview(self) -> None:
                if self._calibration_sender is None:
                    return
                if self._flow.index < 1:
                    return
                zone_count = self._state.effective_device_zone_count()
                frame = [(0, 0, 0)] * zone_count
                mode = str(self.color_mode_combo.currentText())
                gain = 1.0 if mode == "dynamic" else 0.7
                vibrancy = float(self.vibrancy_slider.value()) / 100.0
                for i in range(zone_count):
                    phase = (i + self._preview_phase) % max(1, zone_count)
                    ramp = phase / max(1, zone_count - 1)
                    red = int(min(255, 255 * ramp * gain * vibrancy))
                    green = int(min(255, 255 * (1.0 - ramp) * 0.8 * vibrancy))
                    blue = int(min(255, 150 + (80 if mode == "dynamic" else 0)))
                    frame[i] = (red, green, blue)
                self._preview_phase = (self._preview_phase + (3 if mode == "dynamic" else 1)) % max(1, zone_count)
                try:
                    self._calibration_sender(frame)
                except Exception:
                    _log.exception("Live preview sender failed; disabling preview updates")
                    self._calibration_sender = None
                    self._stop_live_preview()

            def _ensure_live_preview_running(self) -> None:
                if self._calibration_sender is None:
                    return
                if self._live_preview_timer is None:
                    return
                is_active = getattr(self._live_preview_timer, "isActive", None)
                start = getattr(self._live_preview_timer, "start", None)
                if callable(is_active) and callable(start) and not is_active():
                    start()

            def _stop_live_preview(self) -> None:
                if self._live_preview_timer is None:
                    return
                stop = getattr(self._live_preview_timer, "stop", None)
                if callable(stop):
                    stop()

            def _next_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step + 1) % self._state.cycle_length(self._current_calibration_mode())
                self._refresh()
                self._send_test_pattern()

            def _prev_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step - 1) % self._state.cycle_length(self._current_calibration_mode())
                self._refresh()
                self._send_test_pattern()

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()

    def in_progress_config(self) -> AppConfig:
        return self._dialog.in_progress_config()
