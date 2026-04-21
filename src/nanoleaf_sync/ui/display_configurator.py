from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_state import CalibrationState, TEST_MODES, build_testing_panel_state
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

MAX_WIZARD_ZONE_COUNT = 128
CORNER_OFFSET_LIMIT = 24
CALIBRATION_MODE_CORNER = "corner+offset alignment"
WIZARD_STEPS: tuple[str, ...] = (
    "Welcome & Display",
    "Color & HDR",
    "Zone Basics",
    "Calibration Check",
    "Review & Finish",
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
    def setLayout(self, *_args, **_kwargs) -> None:
        return None


def _qt_widget(qt: dict[str, object], name: str, fallback):
    return qt.get(name, fallback)


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

    def __init__(self, parent, cfg: AppConfig, *, calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QLabel = qt["QLabel"]
        QVBoxLayout = qt["QVBoxLayout"]
        QGridLayout = qt["QGridLayout"]
        QComboBox = qt["QComboBox"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]
        QStackedWidget = _qt_widget(qt, "QStackedWidget", _FallbackStackedWidget)
        QWidget = _qt_widget(qt, "QWidget", _FallbackWidget)
        QHBoxLayout = _qt_widget(qt, "QHBoxLayout", _FallbackLayout)

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Setup Wizard")
                resize = getattr(self, "resize", None)
                if callable(resize):
                    resize(700, 560)
                self._calibration_sender = calibration_sender
                self._test_step = 0
                self._state = CalibrationState.from_config(cfg)
                self._flow = WizardFlowState()

                self.step_label = QLabel("")

                # Step 1
                self.display_mode_combo = QComboBox()
                self.display_mode_combo.addItems(["sdr", "hdr"])
                self.display_mode_combo.setCurrentIndex(self.display_mode_combo.findText("hdr" if cfg.hdr_enabled else "sdr"))

                # Step 2
                self.color_mode_combo = QComboBox()
                self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"])
                self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))))
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

                # Step 3
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, MAX_WIZARD_ZONE_COUNT)
                self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_count_value = QLabel("")
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["Edge strip (recommended)", "Full-screen horizontal"])
                self.zone_preset_combo.setCurrentIndex(0 if self._state.zone_preset == "edge-weighted" else 1)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, MAX_WIZARD_ZONE_COUNT)
                self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_value = QLabel("")
                self.device_zone_count_auto_checkbox = qt["QCheckBox"]("Auto-detect strip zone count")
                self.device_zone_count_auto_checkbox.setChecked(self._state.auto_device_zone_count)
                self.device_zone_status = QLabel("")
                self.zone_count_explanation = QLabel("")

                # Step 4
                self.reverse_checkbox = qt["QCheckBox"]("Reverse strip orientation")
                self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-64, 64)
                self.zone_offset_slider.setValue(self._state.zone_offset)
                self.zone_offset_value = QLabel("")
                self.preview_text = QLabel("")
                self.preview_visual = QLabel("")
                self.calibration_test_label = QLabel("")
                self.calibration_next_button = QPushButton("Next test zone")
                self.calibration_prev_button = QPushButton("Previous")
                self.calibration_send_button = QPushButton("Send test pattern")
                self.assign_tl_button = QPushButton("Assign current zone → Top-left")
                self.assign_tr_button = QPushButton("Assign current zone → Top-right")
                self.assign_br_button = QPushButton("Assign current zone → Bottom-right")
                self.assign_bl_button = QPushButton("Assign current zone → Bottom-left")
                self.current_zone_label = QLabel("")

                # Step 5
                self.summary_label = QLabel("")

                self.cancel_button = QPushButton("Cancel")
                self.back_button = QPushButton("Back")
                self.next_button = QPushButton("Next")
                self.finish_button = QPushButton("Finish")
                self.cancel_button.clicked.connect(self.reject)
                self.back_button.clicked.connect(self._go_back)
                self.next_button.clicked.connect(self._go_next)
                self.finish_button.clicked.connect(self.accept)

                for signal in (
                    self.display_mode_combo.currentIndexChanged,
                    self.zone_count_slider.valueChanged,
                    self.zone_offset_slider.valueChanged,
                    self.zone_preset_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                    self.device_zone_count_slider.valueChanged,
                    self.device_zone_count_auto_checkbox.stateChanged,
                ):
                    signal.connect(self._refresh)

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
                self.pages.addWidget(self._build_step_4(QWidget, QGridLayout, QLabel))
                self.pages.addWidget(self._build_step_5(QWidget, QVBoxLayout, QLabel))

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
                self._set_tooltip(self.zone_offset_slider, "Shifts the strip mapping ring by whole zones.")
                self._set_tooltip(self.reverse_checkbox, "Flip mapping direction if strip order is reversed.")
                self._set_tooltip(self.calibration_send_button, "Send a fresh calibration frame to the strip right now.")
                self._set_tooltip(self.calibration_next_button, "Move to the next physical strip zone and transmit it.")
                self._set_tooltip(self.calibration_prev_button, "Move to the previous physical strip zone and transmit it.")
                self._set_tooltip(self.assign_tl_button, "Assign the currently lit strip zone as top-left screen corner.")
                self._set_tooltip(self.assign_tr_button, "Assign the currently lit strip zone as top-right screen corner.")
                self._set_tooltip(self.assign_br_button, "Assign the currently lit strip zone as bottom-right screen corner.")
                self._set_tooltip(self.assign_bl_button, "Assign the currently lit strip zone as bottom-left screen corner.")

            def _build_step_1(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(6)
                layout.addWidget(QLabel("Welcome. Choose your display mode first."), 0, 0, 1, 2)
                layout.addWidget(QLabel("HDR mode unlocks HDR transfer/primaries/brightness controls in the next step."), 1, 0, 1, 2)
                layout.addWidget(QLabel("SDR mode keeps a simpler color path for lower-latency setups."), 2, 0, 1, 2)
                layout.addWidget(QLabel("SDR / HDR mode"), 3, 0)
                layout.addWidget(self.display_mode_combo, 3, 1)
                row_stretch = getattr(layout, "setRowStretch", None)
                if callable(row_stretch):
                    row_stretch(4, 1)
                page.setLayout(layout)
                return page

            def _build_step_2(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(6)
                layout.addWidget(QLabel("Configure color behavior for the chosen mode."), 0, 0, 1, 3)
                layout.addWidget(QLabel("Colour behavior"), 1, 0)
                layout.addWidget(self.color_mode_combo, 1, 1, 1, 2)
                layout.addWidget(self.hdr_transfer_label, 2, 0)
                layout.addWidget(self.hdr_transfer_combo, 2, 1, 1, 2)
                layout.addWidget(self.hdr_primaries_label, 3, 0)
                layout.addWidget(self.hdr_primaries_combo, 3, 1, 1, 2)
                layout.addWidget(self.hdr_max_nits_label, 4, 0)
                layout.addWidget(self.hdr_max_nits_slider, 4, 1)
                layout.addWidget(self.hdr_max_nits_value, 4, 2)
                row_stretch = getattr(layout, "setRowStretch", None)
                if callable(row_stretch):
                    row_stretch(5, 1)
                page.setLayout(layout)
                return page

            def _build_step_3(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(6)
                layout.addWidget(QLabel("Set strip and zone basics."), 0, 0, 1, 3)
                layout.addWidget(QLabel("Source zone count"), 1, 0)
                layout.addWidget(self.zone_count_slider, 1, 1)
                layout.addWidget(self.zone_count_value, 1, 2)
                layout.addWidget(QLabel("Zone layout preset"), 2, 0)
                layout.addWidget(self.zone_preset_combo, 2, 1, 1, 2)
                layout.addWidget(QLabel("Device zone count"), 3, 0)
                layout.addWidget(self.device_zone_count_slider, 3, 1)
                layout.addWidget(self.device_zone_count_value, 3, 2)
                layout.addWidget(self.device_zone_count_auto_checkbox, 4, 0, 1, 3)
                layout.addWidget(self.zone_count_explanation, 5, 0, 1, 3)
                layout.addWidget(self.device_zone_status, 6, 0, 1, 3)
                row_stretch = getattr(layout, "setRowStretch", None)
                if callable(row_stretch):
                    row_stretch(7, 1)
                page.setLayout(layout)
                return page

            def _build_step_4(self, QWidget, QGridLayout, QLabel):
                page = QWidget()
                layout = QGridLayout()
                if hasattr(layout, "setVerticalSpacing"):
                    layout.setVerticalSpacing(6)
                layout.addWidget(QLabel(f"Calibration and testing\n{calibration_sequence_text()}"), 0, 0, 1, 3)
                layout.addWidget(QLabel("Zone offset"), 1, 0)
                layout.addWidget(self.zone_offset_slider, 1, 1)
                layout.addWidget(self.zone_offset_value, 1, 2)
                layout.addWidget(self.reverse_checkbox, 2, 0, 1, 2)
                layout.addWidget(QLabel("Calibration method: corner anchors + offset"), 3, 0, 1, 3)
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
                layout.addWidget(self.calibration_test_label, 13, 0, 1, 3)
                row_stretch = getattr(layout, "setRowStretch", None)
                if callable(row_stretch):
                    row_stretch(14, 1)
                page.setLayout(layout)
                return page

            def _build_step_5(self, QWidget, QVBoxLayout, QLabel):
                page = QWidget()
                layout = QVBoxLayout()
                set_spacing = getattr(layout, "setSpacing", None)
                if callable(set_spacing):
                    set_spacing(6)
                layout.addWidget(QLabel("Summary"))
                layout.addWidget(self.summary_label)
                page.setLayout(layout)
                return page

            def _go_next(self) -> None:
                self._flow.next()
                self._refresh()

            def _go_back(self) -> None:
                self._flow.back()
                self._refresh()

            def _pull_state_from_controls(self) -> None:
                self._state.zone_count = int(self.zone_count_slider.value())
                self._state.zone_preset = "edge-weighted" if str(self.zone_preset_combo.currentText()).startswith("Edge strip") else "horizontal"
                self._state.zone_offset = int(self.zone_offset_slider.value())
                self._state.reverse_zones = bool(self.reverse_checkbox.isChecked())
                self._state.device_zone_count = int(self.device_zone_count_slider.value())
                self._state.auto_device_zone_count = bool(self.device_zone_count_auto_checkbox.isChecked())
                self._state.corner_offsets_enabled = False
                self._state.corner_zone_offsets = [0, 0, 0, 0]

            def _refresh(self) -> None:
                self._pull_state_from_controls()
                self.pages.setCurrentIndex(self._flow.index)
                self.step_label.setText(self._flow.step_label())
                back_set_enabled = getattr(self.back_button, "setEnabled", None)
                if callable(back_set_enabled):
                    back_set_enabled(self._flow.can_go_back())
                next_set_enabled = getattr(self.next_button, "setEnabled", None)
                if callable(next_set_enabled):
                    next_set_enabled(self._flow.can_go_next())
                finish_set_enabled = getattr(self.finish_button, "setEnabled", None)
                if callable(finish_set_enabled):
                    finish_set_enabled(not self._flow.can_go_next())

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
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                self.device_zone_count_slider.setEnabled(not self.device_zone_count_auto_checkbox.isChecked())
                self.device_zone_count_value.setText("auto" if self.device_zone_count_auto_checkbox.isChecked() else str(self.device_zone_count_slider.value()))
                self.zone_count_explanation.setText(
                    "Source zones = sampling regions on the screen. Device zones = strip output LEDs / cycle length."
                )
                self.device_zone_status.setText(self._state.auto_detection_status())

                preview = build_testing_panel_state(
                    state=self._state,
                    runtime_status={},
                    cfg=cfg,
                    mode=CALIBRATION_MODE_CORNER,
                    step=self._test_step,
                )
                self.preview_text.setText(self._state.mapping_preview_text())
                self.preview_visual.setText(self._state.mapping_preview_visual())
                self.calibration_test_label.setText(preview.active_test_description)
                current_zone = self._state.step_for_mode(
                    CALIBRATION_MODE_CORNER,
                    self._test_step,
                ).device_zone_index
                self.current_zone_label.setText(f"Current physical strip zone: {current_zone}")
                self.summary_label.setText(
                    "\n".join(
                        (
                            f"Display mode: {self.display_mode_combo.currentText()}",
                            f"Color mode: {self.color_mode_combo.currentText()}",
                            f"Zone preset: {self._state.zone_preset}",
                            f"Source zones: {self._state.zone_count}",
                            f"Effective strip zones: {self._state.effective_device_zone_count()}",
                            "Calibration method: corner anchors + offset",
                            self._state.auto_detection_status(),
                        )
                    )
                )

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
                    corner_offsets_enabled=bool(self._state.corner_offsets_enabled),
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    wizard_completed=True,
                )

            def _assign_anchor(self, corner: str) -> None:
                current_zone = self._state.step_for_mode(
                    CALIBRATION_MODE_CORNER,
                    self._test_step,
                ).device_zone_index
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
                mode = CALIBRATION_MODE_CORNER
                off_frame = [(0, 0, 0)] * self._state.effective_device_zone_count()
                self._calibration_sender(off_frame)
                self._calibration_sender(self._state.frame_for_step(mode=mode, step=self._test_step, brightness=1.0, all_off_except_active=True))

            def _next_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step + 1) % self._state.cycle_length(CALIBRATION_MODE_CORNER)
                self._refresh()
                self._send_test_pattern()

            def _prev_test_zone(self) -> None:
                self._pull_state_from_controls()
                self._test_step = (self._test_step - 1) % self._state.cycle_length(CALIBRATION_MODE_CORNER)
                self._refresh()
                self._send_test_pattern()

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
