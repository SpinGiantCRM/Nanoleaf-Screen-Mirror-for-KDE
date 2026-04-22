from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_state import CalibrationState, build_testing_panel_state
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

MAX_WIZARD_ZONE_COUNT = 128
CALIBRATION_MODE_WIZARD = "start-point identification"
WIZARD_STEPS: tuple[str, ...] = (
    "Calibration",
    "Display Preset",
    "Look & Feel",
)
_log = logging.getLogger(__name__)

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

    def can_go_back(self) -> bool:
        return self.index > 0

    def can_go_next(self) -> bool:
        return self.index < (self.total_steps - 1)

    def step_label(self) -> str:
        return f"Step {self.index + 1}/{self.total_steps}: {WIZARD_STEPS[self.index]}"

    def next(self) -> None:
        if self.can_go_next():
            self.index += 1

    def back(self) -> None:
        if self.can_go_back():
            self.index -= 1


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
                status = runtime_status or {}
                detected_device_zone_count = int(status.get("device_zone_count") or 0)
                self._requires_manual_device_zone_count = (
                    int(getattr(cfg, "device_zone_count", 0)) <= 0 and detected_device_zone_count <= 0
                )
                self._device_zone_count_confirmed = not self._requires_manual_device_zone_count
                if int(getattr(cfg, "device_zone_count", 0)) <= 0 and detected_device_zone_count > 0:
                    self._state.device_zone_count = detected_device_zone_count

                self.step_label = QLabel("")
                self._preview_phase = 0
                self._first_run_defaults = not bool(getattr(cfg, "wizard_completed", False))
                self._live_preview_timer = QTimer(self) if callable(QTimer) else None

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

                # Step 1
                self.reverse_checkbox = qt["QCheckBox"]("Reverse strip orientation")
                self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                initial_offset_limit = max(1, self._state.effective_device_zone_count() - 1)
                self.zone_offset_slider.setRange(-initial_offset_limit, initial_offset_limit)
                self.zone_offset_slider.setValue(self._state.zone_offset)
                self.zone_offset_value = QLabel("")
                self.test_step_index_value = QLabel("")
                self.preview_text = QLabel("")
                self.preview_visual = QLabel("")
                self.calibration_test_label = QLabel("")
                self.anchor_validation_label = QLabel("")
                self.calibration_next_button = QPushButton("Next test zone step")
                self.calibration_prev_button = QPushButton("Previous test zone step")
                self.calibration_send_button = QPushButton("Send test pattern")
                self.assign_tl_button = QPushButton("Assign current zone → Top-left")
                self.assign_tr_button = QPushButton("Assign current zone → Top-right")
                self.assign_br_button = QPushButton("Assign current zone → Bottom-right")
                self.assign_bl_button = QPushButton("Assign current zone → Bottom-left")
                self.current_zone_label = QLabel("")
                self.advanced_calibration_group = QGroupBox("Advanced calibration")
                set_checkable = getattr(self.advanced_calibration_group, "setCheckable", None)
                if callable(set_checkable):
                    set_checkable(True)
                    self.advanced_calibration_group.setChecked(False)
                self.calibration_hint = QLabel("Align strip start and orientation, then continue.")

                # Summary
                self.summary_label = QLabel("")

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
                self.calibration_next_button.clicked.connect(self._next_test_zone)
                self.calibration_prev_button.clicked.connect(self._prev_test_zone)
                self.calibration_send_button.clicked.connect(self._send_test_pattern)
                self.assign_tl_button.clicked.connect(lambda: self._assign_anchor("top_left"))
                self.assign_tr_button.clicked.connect(lambda: self._assign_anchor("top_right"))
                self.assign_br_button.clicked.connect(lambda: self._assign_anchor("bottom_right"))
                self.assign_bl_button.clicked.connect(lambda: self._assign_anchor("bottom_left"))

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
                layout.addWidget(QLabel(f"Calibration and testing\n{calibration_sequence_text()}"), 0, 0, 1, 3)
                layout.addWidget(self.calibration_hint, 1, 0, 1, 3)
                layout.addWidget(QLabel("Strip LED zone count"), 2, 0)
                layout.addWidget(self.device_zone_count_slider, 2, 1)
                layout.addWidget(self.device_zone_count_value, 2, 2)
                layout.addWidget(self.device_zone_status, 3, 0, 1, 3)
                layout.addWidget(self.preview_text, 4, 0, 1, 3)
                layout.addWidget(self.preview_visual, 5, 0, 1, 3)
                layout.addWidget(self.calibration_next_button, 6, 0, 1, 2)
                layout.addWidget(self.calibration_prev_button, 6, 2)
                layout.addWidget(self.calibration_send_button, 7, 0, 1, 3)
                layout.addWidget(self.current_zone_label, 8, 0, 1, 3)
                layout.addWidget(self.assign_tl_button, 9, 0, 1, 3)
                layout.addWidget(self.assign_tr_button, 10, 0, 1, 3)
                layout.addWidget(self.assign_br_button, 11, 0, 1, 3)
                layout.addWidget(self.assign_bl_button, 12, 0, 1, 3)
                layout.addWidget(self.anchor_validation_label, 13, 0, 1, 3)
                layout.addWidget(self.calibration_test_label, 14, 0, 1, 3)

                advanced_layout = QGridLayout()
                advanced_layout.addWidget(QLabel("Global mapping zone offset"), 0, 0)
                advanced_layout.addWidget(self.zone_offset_slider, 0, 1)
                advanced_layout.addWidget(self.zone_offset_value, 0, 2)
                advanced_layout.addWidget(self.reverse_checkbox, 1, 0, 1, 2)
                advanced_layout.addWidget(QLabel("Test zone step index"), 2, 0)
                advanced_layout.addWidget(self.test_step_index_value, 2, 1, 1, 2)
                self.advanced_calibration_group.setLayout(advanced_layout)
                layout.addWidget(self.advanced_calibration_group, 15, 0, 1, 3)
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
                self._state.calibration_model = str(getattr(cfg, "calibration_model", "offset_direction"))

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
                step_total = self._state.cycle_length(CALIBRATION_MODE_WIZARD)
                self._test_step %= step_total
                return self._state.step_for_mode(CALIBRATION_MODE_WIZARD, self._test_step)

            def _on_device_zone_count_changed(self, *_args) -> None:
                previous_zone_count = self._state.effective_device_zone_count()
                self._device_zone_count_confirmed = True
                self._sync_zone_offset_slider(previous_zone_count=previous_zone_count)
                self._refresh()

            def _refresh(self) -> None:
                self._pull_state_from_controls()
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
                corner_mode = self._state.calibration_model == "corner_anchored"
                anchors = {
                    "top_left": self._state.corner_anchor_top_left if self._state.corner_anchor_top_left >= 0 else None,
                    "top_right": self._state.corner_anchor_top_right if self._state.corner_anchor_top_right >= 0 else None,
                    "bottom_right": self._state.corner_anchor_bottom_right if self._state.corner_anchor_bottom_right >= 0 else None,
                    "bottom_left": self._state.corner_anchor_bottom_left if self._state.corner_anchor_bottom_left >= 0 else None,
                }
                anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=effective_zone_count)
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
                    "" if not corner_mode else ("Corner anchors complete." if anchor_validation.valid else "Anchor validation error: " + " ".join(anchor_validation.errors))
                )

                finish_set_enabled = getattr(self.finish_button, "setEnabled", None)
                if callable(finish_set_enabled):
                    finish_set_enabled(
                        not self._flow.can_go_next()
                        and self._device_zone_count_confirmed
                        and (not corner_mode or anchor_validation.valid)
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
                    mode=CALIBRATION_MODE_WIZARD,
                    step=self._test_step,
                )
                self.preview_text.setText(self._state.mapping_preview_text())
                self.preview_visual.setText(self._state.mapping_preview_visual())
                self.calibration_test_label.setText(preview.active_test_description)
                active_step = self._active_calibration_step()
                current_zone = active_step.device_zone_index
                step_total = self._state.cycle_length(CALIBRATION_MODE_WIZARD)
                self.test_step_index_value.setText(f"{self._test_step + 1}/{step_total}")
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
                            "Calibration method: zone walk + offset",
                            device_zone_status_text,
                        )
                    )
                )
                if self._flow.index >= 1 and self._calibration_sender is not None:
                    self._ensure_live_preview_running()
                else:
                    self._stop_live_preview()

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
                    led_gamma=float(self.vibrancy_slider.value()) / 100.0,
                    zones=new_zones,
                    zone_preset=self._state.zone_preset,
                    sampling_quality=str(self.sampling_quality_combo.currentText()).lower(),
                    device_zone_count=self._state.device_zone_count,
                    reverse_zones=self._state.reverse_zones,
                    zone_offset=self._state.zone_offset,
                    corner_offsets_enabled=bool(self._state.corner_offsets_enabled),
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    calibration_model=str(self._state.calibration_model),
                    wizard_completed=True,
                )

            def _assign_anchor(self, corner: str) -> None:
                if self._state.calibration_model != "corner_anchored":
                    return
                current_zone = self._active_calibration_step().device_zone_index
                if corner == "top_left":
                    self._state.corner_anchor_top_left = current_zone
                elif corner == "top_right":
                    self._state.corner_anchor_top_right = current_zone
                elif corner == "bottom_right":
                    self._state.corner_anchor_bottom_right = current_zone
                elif corner == "bottom_left":
                    self._state.corner_anchor_bottom_left = current_zone
                self._refresh()

            def _send_test_pattern(self) -> None:
                if self._calibration_sender is None:
                    return
                self._pull_state_from_controls()
                # Normalize self._test_step before generating the frame.
                self._active_calibration_step()
                mode = CALIBRATION_MODE_WIZARD
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
                self._test_step = (self._test_step + 1) % self._state.cycle_length(CALIBRATION_MODE_WIZARD)
                self._refresh()
                self._send_test_pattern()

            def _prev_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step - 1) % self._state.cycle_length(CALIBRATION_MODE_WIZARD)
                self._refresh()
                self._send_test_pattern()

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
