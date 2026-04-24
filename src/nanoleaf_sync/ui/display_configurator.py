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
from nanoleaf_sync.ui.preset_ui import (
    COLOR_STYLE_LABELS,
    DISPLAY_PRESET_LABELS,
    EDGE_LOCALITY_LABELS,
    LAYOUT_PRESET_LABELS,
    MOTION_PRESET_LABELS,
    SAMPLING_QUALITY_LABELS,
    label_for_value,
    labels,
    value_for_label,
)
from nanoleaf_sync.ui.zone_presets import edge_weighted_layout, make_edge_weighted_zones, make_horizontal_zones

MAX_WIZARD_ZONE_COUNT = 128
WIZARD_STEPS: tuple[str, ...] = (
    "Calibration",
    "Display Preset",
    "Look & Feel",
)
CALIBRATION_MODE_PHYSICAL = "physical zone walk"
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
        QCheckBox = qt["QCheckBox"]
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
                self._flow = WizardFlowState()
                self._initial_calibration = cfg.effective_calibration()
                status = runtime_status or {}
                self._state = CalibrationState.from_config(cfg, status)
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
                self._source_zones_locked_to_device_count = (
                    not bool(self._state.source_zones_user_configured)
                    and str(self._state.layout_preset) == "edge-weighted"
                )
                if should_prefer_detected and self._source_zones_locked_to_device_count:
                    self._state.zone_count = max(1, int(detected_device_zone_count))

                self.step_label = QLabel("")
                self._preview_phase = 0
                self._suspend_session_persist = True
                self._first_run_defaults = not bool(getattr(cfg, "wizard_completed", False))
                self._live_preview_timer = QTimer(self) if callable(QTimer) else None
                self._last_preview_refresh_ms = 0.0

                # Step 2
                self.display_preset_combo = QComboBox()
                self.display_preset_combo.addItems(labels(DISPLAY_PRESET_LABELS))
                initial_display_preset = str(getattr(cfg, "display_preset", "hdr"))
                self.display_preset_combo.setCurrentIndex(
                    max(0, self.display_preset_combo.findText(label_for_value(DISPLAY_PRESET_LABELS, initial_display_preset, default="HDR")))
                )
                self.display_mode_help = QLabel("")
                self.compositor_hdr_mode_checkbox = QCheckBox("KDE SDR-on-HDR compensation / compositor HDR mode")
                self.compositor_hdr_mode_checkbox.setChecked(bool(getattr(cfg, "compositor_hdr_mode", False)))
                self.sdr_boost_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.sdr_boost_nits_slider.setRange(80, 400)
                self.sdr_boost_nits_slider.setValue(int(getattr(cfg, "sdr_boost_nits", 80.0)))
                self.sdr_boost_nits_value = QLabel("")
                self.display_advanced_group = QGroupBox("Advanced display details")
                _set_checkable(self.display_advanced_group, True)
                _set_checked(self.display_advanced_group, False)

                # Step 3
                self.layout_preset_combo = QComboBox()
                self.layout_preset_combo.addItems([LAYOUT_PRESET_LABELS[0][0]])
                self.layout_preset_combo.setCurrentIndex(0)
                self.layout_debug_combo = QComboBox()
                self.layout_debug_combo.addItems(labels(LAYOUT_PRESET_LABELS))
                current_layout = "horizontal_debug" if self._state.layout_preset == "horizontal" else str(getattr(cfg, "layout_preset", "edge_strip"))
                self.layout_debug_combo.setCurrentIndex(max(0, self.layout_debug_combo.findText(label_for_value(LAYOUT_PRESET_LABELS, current_layout, default="Edge strip"))))
                self.edge_locality_combo = QComboBox()
                self.edge_locality_combo.addItems(labels(EDGE_LOCALITY_LABELS))
                self.edge_locality_combo.setCurrentIndex(max(0, self.edge_locality_combo.findText(label_for_value(EDGE_LOCALITY_LABELS, str(getattr(cfg, "edge_locality", "tight")), default="Tight"))))
                self.motion_preset_combo = QComboBox()
                self.motion_preset_combo.addItems(labels(MOTION_PRESET_LABELS))
                initial_motion = str(getattr(cfg, "motion_preset", "responsive"))
                self.motion_preset_combo.setCurrentIndex(max(0, self.motion_preset_combo.findText(label_for_value(MOTION_PRESET_LABELS, initial_motion, default="Responsive"))))
                self.color_style_combo = QComboBox()
                self.color_style_combo.addItems(labels(COLOR_STYLE_LABELS))
                self.color_style_combo.setCurrentIndex(max(0, self.color_style_combo.findText(label_for_value(COLOR_STYLE_LABELS, str(getattr(cfg, "color_style", "natural")), default="Natural"))))
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
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, MAX_WIZARD_ZONE_COUNT)
                self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_count_value = QLabel("")
                self.sampling_quality_combo = QComboBox()
                self.sampling_quality_combo.addItems(labels(SAMPLING_QUALITY_LABELS))
                self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(label_for_value(SAMPLING_QUALITY_LABELS, str(getattr(cfg, "sampling_quality", "high")), default="High"))))
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, self._device_zone_count_max())
                self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_value = QLabel("")
                self.device_zone_status = QLabel("")
                self.device_zone_summary = QLabel("")
                self.zone_count_explanation = QLabel("")
                self.zone_change_notice = QLabel("")
                self.advanced_details_group = QGroupBox("Advanced details")
                self.advanced_details = QLabel("")
                self.diagnostics_layout_label = QLabel("")
                _set_checkable(self.advanced_details_group, True)
                _set_checked(self.advanced_details_group, False)

                # Step 1
                self.simple_calibration_widget = SimpleCalibrationWidget(qt=qt, title="Corner calibration")
                self.reverse_checkbox = self.simple_calibration_widget.reverse_orientation_checkbox
                self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.test_step_index_value = self.simple_calibration_widget.step_index_label
                self.preview_text = self.simple_calibration_widget.preview_text_label
                self.preview_visual = self.simple_calibration_widget.preview_visual_label
                self.calibration_test_label = QLabel("")
                self.anchor_validation_label = self.simple_calibration_widget.validation_label
                self.calibration_diagnostics_group = QGroupBox("Diagnostics")
                _set_checkable(self.calibration_diagnostics_group, True)
                _set_checked(self.calibration_diagnostics_group, False)
                self.calibration_diagnostics_label = QLabel("")
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
                    "Use Previous/Next zone to find the right physical LED, assign corners, and adjust reverse orientation if needed."
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
                    self.display_preset_combo.currentIndexChanged,
                    self.sampling_quality_combo.currentIndexChanged,
                    self.motion_preset_combo.currentIndexChanged,
                    self.color_style_combo.currentIndexChanged,
                    self.edge_locality_combo.currentIndexChanged,
                    self.layout_debug_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                ):
                    signal.connect(self._refresh)
                self.zone_count_slider.valueChanged.connect(self._on_zone_count_changed)
                self.device_zone_count_slider.valueChanged.connect(self._on_device_zone_count_changed)
                self._on_device_zone_count_changed(refresh=False)
                self.display_advanced_group.toggled.connect(
                    lambda checked: self._set_group_contents_visible(self.display_advanced_group, bool(checked))
                )
                self.advanced_details_group.toggled.connect(
                    lambda checked: self._set_group_contents_visible(self.advanced_details_group, bool(checked))
                )
                self.calibration_diagnostics_group.toggled.connect(
                    lambda checked: self._set_group_contents_visible(self.calibration_diagnostics_group, bool(checked))
                )

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
                    on_flash_assigned_corners=self._flash_assigned_corners,
                    on_walk_strip_once=self._walk_strip_once,
                )
                self.calibration_send_button.clicked.connect(self._send_test_pattern)

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

            def _set_group_contents_visible(self, group, visible: bool) -> None:
                layout = getattr(group, "layout", lambda: None)()
                if layout is None:
                    return
                for idx in range(layout.count()):
                    item = layout.itemAt(idx)
                    widget = item.widget() if item is not None else None
                    if widget is not None:
                        set_visible = getattr(widget, "setVisible", None)
                        if callable(set_visible):
                            set_visible(bool(visible))

            def _set_tooltip(self, widget, text: str) -> None:
                setter = getattr(widget, "setToolTip", None)
                if callable(setter):
                    setter(text)

            def _configure_tooltips(self) -> None:
                self._set_tooltip(self.reverse_checkbox, "Flip mapping direction if strip order is reversed.")
                self._set_tooltip(self.calibration_send_button, "Send a fresh calibration frame to the strip right now.")
                self._set_tooltip(self.calibration_next_button, "Move to the next test zone step and transmit it.")
                self._set_tooltip(self.calibration_prev_button, "Move to the previous test zone step and transmit it.")
                self._set_tooltip(self.assign_tl_button, "Assign the currently lit strip zone as top-left screen corner.")
                self._set_tooltip(self.assign_tr_button, "Assign the currently lit strip zone as top-right screen corner.")
                self._set_tooltip(self.assign_br_button, "Assign the currently lit strip zone as bottom-right screen corner.")
                self._set_tooltip(self.assign_bl_button, "Assign the currently lit strip zone as bottom-left screen corner.")
                self._set_tooltip(self.reset_anchors_button, "Clear all corner assignments and start anchor placement again.")
                self._set_tooltip(self.compositor_hdr_mode_checkbox, "Enable compensation when KDE Plasma maps SDR into HDR output.")
                self._set_tooltip(self.sdr_boost_nits_slider, "Plasma SDR white reference in nits when compositor HDR mode is enabled.")
                self._set_tooltip(self.edge_locality_combo, "Tight: most accurate/least bleed. Balanced: softer ambient look. Wide: cinematic blend.")
                self._set_tooltip(self.motion_preset_combo, "Calm: smoother/slower. Responsive: recommended. Dynamic: punchier and reactive.")
                self._set_tooltip(self.color_style_combo, "Natural: accurate colour. Vivid: richer colour. Punchy: strongest effect.")

            def _build_step_1(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Calibration"), 0, 0, 1, 3)
                layout.addWidget(self.calibration_hint, 1, 0, 1, 3)
                row = self.simple_calibration_widget.add_to_layout(layout, row=2, include_header=False)
                layout.addWidget(self.calibration_send_button, row, 0, 1, 3); row += 1
                layout.addWidget(self.zone_change_notice, row, 0, 1, 3); row += 1
                diagnostics_layout = QGridLayout()
                diagnostics_layout.addWidget(QLabel("Strip LED zone count"), 0, 0)
                diagnostics_layout.addWidget(self.device_zone_count_slider, 0, 1)
                diagnostics_layout.addWidget(self.device_zone_count_value, 0, 2)
                diagnostics_layout.addWidget(self.device_zone_status, 1, 0, 1, 3)
                diagnostics_layout.addWidget(self.calibration_diagnostics_label, 2, 0, 1, 3)
                self.calibration_diagnostics_group.setLayout(diagnostics_layout)
                layout.addWidget(self.calibration_diagnostics_group, row, 0, 1, 3)
                page.setLayout(layout)
                return page

            def _build_step_2(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Display mode"), 0, 0)
                layout.addWidget(self.display_preset_combo, 0, 1, 1, 2)
                layout.addWidget(self.display_mode_help, 1, 0, 1, 3)
                advanced_layout = QGridLayout()
                advanced_layout.addWidget(self.hdr_transfer_label, 0, 0)
                advanced_layout.addWidget(self.hdr_transfer_combo, 0, 1, 1, 2)
                advanced_layout.addWidget(self.hdr_primaries_label, 1, 0)
                advanced_layout.addWidget(self.hdr_primaries_combo, 1, 1, 1, 2)
                advanced_layout.addWidget(self.hdr_max_nits_label, 2, 0)
                advanced_layout.addWidget(self.hdr_max_nits_slider, 2, 1)
                advanced_layout.addWidget(self.hdr_max_nits_value, 2, 2)
                advanced_layout.addWidget(self.compositor_hdr_mode_checkbox, 3, 0, 1, 3)
                advanced_layout.addWidget(QLabel("SDR white reference"), 4, 0)
                advanced_layout.addWidget(self.sdr_boost_nits_slider, 4, 1)
                advanced_layout.addWidget(self.sdr_boost_nits_value, 4, 2)
                self.display_advanced_group.setLayout(advanced_layout)
                layout.addWidget(self.display_advanced_group, 2, 0, 1, 3)
                page.setLayout(layout)
                return page

            def _build_step_3(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(4)
                layout.addWidget(QLabel("Look & Feel"), 0, 0, 1, 3)

                appearance = QGroupBox("Appearance")
                appearance_layout = QGridLayout()
                appearance_layout.addWidget(QLabel("Layout"), 0, 0)
                appearance_layout.addWidget(self.layout_preset_combo, 0, 1, 1, 2)
                appearance_layout.addWidget(QLabel("Edge locality"), 1, 0)
                appearance_layout.addWidget(self.edge_locality_combo, 1, 1, 1, 2)
                appearance_layout.addWidget(QLabel("Quality"), 2, 0)
                appearance_layout.addWidget(self.sampling_quality_combo, 2, 1, 1, 2)
                appearance_layout.addWidget(QLabel("Motion"), 3, 0)
                appearance_layout.addWidget(self.motion_preset_combo, 3, 1, 1, 2)
                appearance_layout.addWidget(QLabel("Color style"), 4, 0)
                appearance_layout.addWidget(self.color_style_combo, 4, 1, 1, 2)
                appearance.setLayout(appearance_layout)
                layout.addWidget(appearance, 1, 0, 1, 3)

                layout_group = QGroupBox("Layout")
                layout_group_layout = QGridLayout()
                layout_group_layout.addWidget(QLabel("Screen sampling zones"), 0, 0)
                layout_group_layout.addWidget(self.zone_count_slider, 0, 1)
                layout_group_layout.addWidget(self.zone_count_value, 0, 2)
                layout_group_layout.addWidget(QLabel("Strip LED zones"), 1, 0)
                layout_group_layout.addWidget(self.device_zone_summary, 1, 1, 1, 2)
                layout_group.setLayout(layout_group_layout)
                layout.addWidget(layout_group, 2, 0, 1, 3)

                advanced_layout = QGridLayout()
                advanced_layout.addWidget(self.zone_count_explanation, 0, 0, 1, 3)
                advanced_layout.addWidget(self.summary_label, 1, 0, 1, 3)
                advanced_layout.addWidget(self.advanced_details, 2, 0, 1, 3)
                advanced_layout.addWidget(QLabel("Layout (Advanced/Debug)"), 3, 0)
                advanced_layout.addWidget(self.layout_debug_combo, 3, 1, 1, 2)
                advanced_layout.addWidget(self.diagnostics_layout_label, 4, 0, 1, 3)
                advanced_layout.addWidget(self.finish_policy_note, 5, 0, 1, 3)
                self.advanced_details_group.setLayout(advanced_layout)
                layout.addWidget(self.advanced_details_group, 3, 0, 1, 3)
                page.setLayout(layout)
                return page

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
                selected_layout = value_for_label(
                    LAYOUT_PRESET_LABELS,
                    str(self.layout_debug_combo.currentText()),
                    default="edge_strip",
                )
                self._state.layout_preset = selected_layout
                self._state.reverse_zones = bool(self.reverse_checkbox.isChecked())
                self._state.device_zone_count = int(self.device_zone_count_slider.value())
                self._state.calibration_model = "corner_anchored"

            def _remap_zone_index_between_counts(self, zone_index: int, previous_count: int, new_count: int) -> int:
                if int(zone_index) < 0:
                    return -1
                previous_total = max(1, int(previous_count))
                new_total = max(1, int(new_count))
                scaled = int(round((int(zone_index) / previous_total) * new_total)) % new_total
                return scaled

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

            def _active_calibration_step(self):
                step_total = self._state.cycle_length(CALIBRATION_MODE_PHYSICAL)
                self._test_step %= step_total
                return self._state.step_for_mode(CALIBRATION_MODE_PHYSICAL, self._test_step)

            def _current_calibration_mode(self) -> str:
                return CALIBRATION_MODE_PHYSICAL

            def _device_zone_count_max(self) -> int:
                detected = int(self._state.detected_device_zone_count)
                if detected > 0:
                    return max(1, detected)
                return MAX_WIZARD_ZONE_COUNT

            def _on_device_zone_count_changed(self, *_args, refresh: bool = True) -> None:
                previous_zone_count = self._state.effective_device_zone_count()
                self._device_zone_count_confirmed = True
                max_zone_count = self._device_zone_count_max()
                requested_zone_count = int(self.device_zone_count_slider.value())
                clamped_zone_count = max(1, min(requested_zone_count, max_zone_count))
                if requested_zone_count != clamped_zone_count:
                    self._set_slider_value_safely(self.device_zone_count_slider, clamped_zone_count)
                    self.zone_change_notice.setText(
                        f"Strip LED zone count capped at detected hardware count ({max_zone_count})."
                    )
                new_zone_count = max(1, int(self.device_zone_count_slider.value()))
                if self._source_zones_locked_to_device_count:
                    self._set_slider_value_safely(self.zone_count_slider, new_zone_count)
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
                    if requested_zone_count == clamped_zone_count:
                        self.zone_change_notice.setText(
                            "Strip zone count changed: remapped corner anchors and reset calibration test step to 1."
                        )
                if refresh:
                    self._refresh()

            def _on_zone_count_changed(self, *_args) -> None:
                self._source_zones_locked_to_device_count = False
                self._state.source_zones_user_configured = True
                self._refresh()

            def _on_zone_preset_changed(self, *_args) -> None:
                if value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_debug_combo.currentText()), default="edge_strip") != "edge_strip":
                    self._source_zones_locked_to_device_count = False
                self._refresh()

            def _refresh(self) -> None:
                refresh_started = perf_counter()
                self._pull_state_from_controls()
                if not bool(self._suspend_session_persist):
                    self._save_wizard_session()
                self.pages.setCurrentIndex(self._flow.index)
                self.step_label.setText(self._flow.step_label())
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
                if not anchor_validation.valid:
                    if any("duplicate" in str(error).lower() for error in anchor_validation.errors):
                        validation_status = "Duplicate corners"
                    elif any("range" in str(error).lower() for error in anchor_validation.errors):
                        validation_status = "Out of range"
                    else:
                        validation_status = "Missing corners"
                elif invalid_anchor_fallback:
                    validation_status = "Out of range"
                else:
                    validation_status = "Complete"
                self.anchor_validation_label.setText(f"Validation: {validation_status}")

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

                hdr_mode = value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="hdr") == "hdr"
                selected_display_mode = value_for_label(
                    DISPLAY_PRESET_LABELS,
                    str(self.display_preset_combo.currentText()),
                    default="hdr",
                )
                if selected_display_mode == "hdr":
                    self.display_mode_help.setText(
                        "HDR: Use HDR transfer defaults for the most vivid color on HDR desktops."
                    )
                    self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText("pq")))
                    self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText("bt2020")))
                elif selected_display_mode == "sdr":
                    self.display_mode_help.setText(
                        "SDR: Uses SDR-safe defaults for consistent color on standard desktop mode."
                    )
                    self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText("srgb")))
                    self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText("bt709")))
                else:
                    self.display_mode_help.setText(
                        "Auto: Switches between SDR and HDR behavior from runtime desktop capability."
                    )
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
                self.sdr_boost_nits_value.setText(f"{self.sdr_boost_nits_slider.value()} nits")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                normalized_offset = 0
                self.device_zone_count_value.setText(str(effective_zone_count))
                self.zone_count_explanation.setText(
                    "Screen sampling zones are sampled perimeter regions on your display."
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
                assigned = {
                    "Top-left": self._state.corner_anchor_top_left >= 0,
                    "Top-right": self._state.corner_anchor_top_right >= 0,
                    "Bottom-right": self._state.corner_anchor_bottom_right >= 0,
                    "Bottom-left": self._state.corner_anchor_bottom_left >= 0,
                }
                self.simple_calibration_widget.assigned_corners_label.setText(
                    "Assigned corners: "
                    + " | ".join(
                        f"{corner}: {'assigned' if is_assigned else 'unassigned'}"
                        for corner, is_assigned in assigned.items()
                    )
                )
                self.simple_calibration_widget.corner_checklist_label.setText(
                    "Corner checklist: Top-left | Top-right | Bottom-right | Bottom-left"
                )
                self.simple_calibration_widget.direction_label.setText(
                    f"Direction: {'Reversed' if self._state.reverse_zones else 'Normal'}"
                )
                self.preview_text.setText(preview.active_test_description)
                self.preview_visual.setText("")
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
                    f"Current LED: {self._test_step + 1} of {step_total}"
                )
                calibration_warnings: list[str] = []
                detected_count = int(self._state.detected_device_zone_count or 0)
                configured_count = int(self._state.device_zone_count or 0)
                source_count = int(self._state.zone_count or 0)
                if detected_count > 0 and configured_count != detected_count:
                    calibration_warnings.append("Configured strip count differs from detected device count.")
                if source_count != configured_count:
                    calibration_warnings.append("Changing strip count may require recalibration.")
                highest_anchor = max(
                    int(self._state.corner_anchor_top_left),
                    int(self._state.corner_anchor_top_right),
                    int(self._state.corner_anchor_bottom_right),
                    int(self._state.corner_anchor_bottom_left),
                )
                if highest_anchor >= configured_count:
                    calibration_warnings.append("Current anchors were assigned for a different strip length.")
                self.zone_change_notice.setText("\n".join(calibration_warnings))
                self.summary_label.setText(
                    "\n".join(
                        (
                            f"Display preset: {self.display_preset_combo.currentText()}",
                            f"Quality: {self.sampling_quality_combo.currentText()}",
                            f"Motion: {self.motion_preset_combo.currentText()}",
                            f"Color style: {self.color_style_combo.currentText()}",
                            f"Edge locality: {self.edge_locality_combo.currentText()}",
                            f"Layout preset: {self._state.layout_preset}",
                            f"Screen sampling zones: {self._state.zone_count}",
                            f"Strip LED zones: {effective_zone_count}",
                        )
                    )
                )
                if self._state.layout_preset == "edge_strip":
                    frame_width = int(getattr(preview, "frame_width", 0) or 16)
                    frame_height = int(getattr(preview, "frame_height", 0) or 9)
                    layout_info = edge_weighted_layout(
                        zone_count=self._state.zone_count,
                        width=frame_width,
                        height=frame_height,
                        edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"),
                    )
                    side_counts = layout_info.side_counts
                    side_counts_text = f"{side_counts[0]}/{side_counts[1]}/{side_counts[2]}/{side_counts[3]}"
                    thickness_text = f"{layout_info.edge_thickness:.3f}"
                    localized_text = "on"
                else:
                    side_counts_text = "n/a"
                    thickness_text = "n/a"
                    localized_text = "off"

                self.advanced_details.setText(
                    "\n".join(
                        (
                            f"Calibration model/internal resolver mode: {self._state.calibration_model}",
                            f"Sampling quality: {self.sampling_quality_combo.currentText()}",
                            "Calibration mode: corner calibration",
                            f"Screen sampling zones: {self._state.zone_count}",
                            f"Strip LED zones: {effective_zone_count}",
                            f"Per-side zone counts (top/right/bottom/left): {side_counts_text}",
                            f"Edge sampling thickness: {thickness_text}",
                            f"Localized edge sampling: {localized_text}",
                            ("Verification: Calibration complete" if not verification.hard_fail else "Verification: Needs corner assignments"),
                            device_zone_status_text,
                        )
                    )
                )
                self.calibration_diagnostics_label.setText(
                    "\n".join(
                        (
                            f"Backend policy/effective backend: {self._state.auto_detection_status()}",
                            f"Detected/configured strip count details: detected={self._state.detected_device_zone_count or 'n/a'}, configured={effective_zone_count}",
                            f"Mapping preview: {self._state.mapping_preview_visual()}",
                            f"Device→source mapping list: {self._state.mapping_preview_text()}",
                        )
                    )
                )
                self._set_group_contents_visible(self.display_advanced_group, bool(self.display_advanced_group.isChecked()))
                self._set_group_contents_visible(self.advanced_details_group, bool(self.advanced_details_group.isChecked()))
                self._set_group_contents_visible(self.calibration_diagnostics_group, bool(self.calibration_diagnostics_group.isChecked()))
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
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
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
                new_zones = make_edge_weighted_zones(zone_count, edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight")) if self._state.layout_preset == "edge_strip" else make_horizontal_zones(zone_count)
                fallback_warning_codes = list(mapping_snapshot.warning_codes)
                fallback_strategy = str(mapping_snapshot.fallback_strategy or "")
                calibration_payload = CalibrationConfig(
                    schema_version=int(getattr(cfg, "calibration_schema_version", 1) or 1),
                    calibration_model="corner_anchored",
                    device_zone_count=int(self._state.device_zone_count),
                    output_channel_order=str(self._initial_calibration.output_channel_order),
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
                )
                return replace(
                    cfg,
                    layout_preset=value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_debug_combo.currentText()), default="edge_strip"),
                    edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"),
                    sampling_quality=value_for_label(SAMPLING_QUALITY_LABELS, str(self.sampling_quality_combo.currentText()), default="high"),
                    motion_preset=value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"),
                    color_style=value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="natural"),
                    display_preset=value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="hdr"),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    led_gamma=cfg.led_gamma,
                    zones=new_zones,
                    device_zone_count=self._state.device_zone_count,
                    reverse_zones=self._state.reverse_zones,
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
                    wizard_in_progress_state="",
                    wizard_completed=True,
                )

            def _serialize_wizard_draft(self) -> str:
                self._pull_state_from_controls()
                mapping_snapshot = resolve_calibration_mapping(
                    zone_count=max(1, int(self._state.zone_count)),
                    device_zone_count=max(1, int(self._state.effective_device_zone_count())),
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
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
                    "layout_preset": str(self._state.layout_preset),
                    "reverse_zones": bool(self._state.reverse_zones),
                    "device_zone_count": int(self._state.device_zone_count),
                    "display_preset": value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="hdr"),
                    "sampling_quality": value_for_label(SAMPLING_QUALITY_LABELS, str(self.sampling_quality_combo.currentText()), default="high"),
                    "motion_preset": value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"),
                    "color_style": value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="natural"),
                    "edge_locality": value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"),
                    "layout_preset": value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_debug_combo.currentText()), default="edge_strip"),
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
                preset = str(data.get("layout_preset", self._state.layout_preset))
                self.layout_debug_combo.setCurrentIndex(0 if preset == "edge_strip" else 1)
                self.reverse_checkbox.setChecked(bool(data.get("reverse_zones", self.reverse_checkbox.isChecked())))
                self.device_zone_count_slider.setValue(int(data.get("device_zone_count", self.device_zone_count_slider.value())))
                display_idx = self.display_preset_combo.findText(label_for_value(DISPLAY_PRESET_LABELS, str(data.get("display_preset", "hdr")), default="HDR"))
                if display_idx >= 0:
                    self.display_preset_combo.setCurrentIndex(display_idx)
                sampling_idx = self.sampling_quality_combo.findText(label_for_value(SAMPLING_QUALITY_LABELS, str(data.get("sampling_quality", "high")), default="High"))
                if sampling_idx >= 0:
                    self.sampling_quality_combo.setCurrentIndex(sampling_idx)
                motion_idx = self.motion_preset_combo.findText(label_for_value(MOTION_PRESET_LABELS, str(data.get("motion_preset", value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"))), default="Responsive"))
                if motion_idx >= 0:
                    self.motion_preset_combo.setCurrentIndex(motion_idx)
                color_style_idx = self.color_style_combo.findText(label_for_value(COLOR_STYLE_LABELS, str(data.get("color_style", value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="natural"))), default="Natural"))
                if color_style_idx >= 0:
                    self.color_style_combo.setCurrentIndex(color_style_idx)
                edge_locality_idx = self.edge_locality_combo.findText(label_for_value(EDGE_LOCALITY_LABELS, str(data.get("edge_locality", "tight")), default="Tight"))
                if edge_locality_idx >= 0:
                    self.edge_locality_combo.setCurrentIndex(edge_locality_idx)
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

            def _flash_assigned_corners(self) -> None:
                self._state.resolved_mapping_snapshot()
                self.preview_text.setText("Flashing assigned corners (TL/TR/BR/BL).")
                self._send_test_pattern()

            def _walk_strip_once(self) -> None:
                self._test_step = 0
                self.preview_text.setText("Walking around strip once from LED 1.")
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
                mode = value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive")
                style = value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="natural")
                gain = 1.0 if mode == "dynamic" else (0.85 if mode == "responsive" else 0.7)
                style_gain = {"natural": 1.0, "vivid": 1.15, "punchy": 1.30}[style]
                for i in range(zone_count):
                    phase = (i + self._preview_phase) % max(1, zone_count)
                    ramp = phase / max(1, zone_count - 1)
                    red = int(min(255, 255 * ramp * gain * style_gain))
                    green = int(min(255, 255 * (1.0 - ramp) * 0.8 * style_gain))
                    blue = int(min(255, 150 + (80 if mode == "dynamic" else 0)))
                    frame[i] = (red, green, blue)
                self._preview_phase = (self._preview_phase + (3 if mode == "dynamic" else (2 if mode == "responsive" else 1))) % max(1, zone_count)
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
