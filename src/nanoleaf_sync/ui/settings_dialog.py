from __future__ import annotations

from dataclasses import replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    backend_selection_info,
    build_latency_result,
    latency_result_summary,
    should_auto_run_latency_probe,
    build_testing_panel_state,
)
from nanoleaf_sync.ui.calibration_widget import SimpleCalibrationWidget
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
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text as _mapping_preview_text
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

FPS_MIN = 1
FPS_MAX = 120
HDR_MAX_NITS_MIN = 80
HDR_MAX_NITS_MAX = 10000
MAX_ZONE_COUNT = 128
SDR_BOOST_NITS_MIN = 80
SDR_BOOST_NITS_MAX = 400
CALIBRATION_MODE_PHYSICAL = "physical zone walk"

SETTINGS_SECTIONS: tuple[str, ...] = (
    "Display & Color",
    "Performance",
    "Edge Mapping",
    "Calibration",
    "Device",
    "Diagnostics",
)

class _FallbackLayout:
    def addWidget(self, *_args, **_kwargs) -> None:
        return None

    def addLayout(self, *_args, **_kwargs) -> None:
        return None

    def addStretch(self, *_args, **_kwargs) -> None:
        return None


class _FallbackWidget:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def setLayout(self, *_args, **_kwargs) -> None:
        return None


class _FallbackScrollArea:
    def setWidgetResizable(self, *_args, **_kwargs) -> None:
        return None

    def setWidget(self, *_args, **_kwargs) -> None:
        return None




def mapping_preview_text(**kwargs) -> str:
    return _mapping_preview_text(**kwargs)


def _qt_widget(qt: dict[str, object], name: str, fallback):
    return qt.get(name, fallback)


class SettingsDialog:
    def __init__(
        self,
        parent,
        cfg: AppConfig,
        *,
        calibration_sender: Callable[[list[tuple[int, int, int]]], None] | None = None,
        runtime_status: dict | None = None,
        initial_section: str | None = None,
    ):
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
        QScrollArea = _qt_widget(qt, "QScrollArea", _FallbackScrollArea)
        QVBoxLayout = _qt_widget(qt, "QVBoxLayout", _FallbackLayout)
        QGroupBox = _qt_widget(qt, "QGroupBox", _FallbackWidget)
        QWidget = _qt_widget(qt, "QWidget", _FallbackWidget)

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("nanoleaf-kde-sync Settings")
                resize = getattr(self, "resize", None)
                if callable(resize):
                    resize(860, 760)
                self._open_display_configurator = False
                self._calibration_sender = calibration_sender
                self._runtime_status = runtime_status or {}
                self._state = CalibrationState.from_config(cfg, runtime_status)
                self._source_zones_locked_to_device_count = (
                    not bool(self._state.source_zones_user_configured)
                    and str(self._state.zone_preset) == "edge-weighted"
                )
                self._test_step = 0
                self._latest_latency = None
                self._section_widgets: dict[str, object] = {}
                self._settings_scroll = None

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.brightness_slider.setRange(0, 100); self.brightness_slider.setValue(int(round(cfg.brightness * 100)))
                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_slider.setRange(0, 100); self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))
                self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_speed_slider.setRange(0, 400); self.smoothing_speed_slider.setValue(int(round(getattr(cfg, "smoothing_speed", 0.75) * 100)))
                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.fps_slider.setRange(FPS_MIN, FPS_MAX); self.fps_slider.setValue(int(cfg.fps))
                self.display_preset_combo = QComboBox(); self.display_preset_combo.addItems(labels(DISPLAY_PRESET_LABELS)); self.display_preset_combo.setCurrentIndex(max(0, self.display_preset_combo.findText(label_for_value(DISPLAY_PRESET_LABELS, str(getattr(cfg, "display_preset", "hdr" if cfg.hdr_enabled else "sdr")), default="SDR"))))
                self.compositor_hdr_mode_checkbox = QCheckBox("Compositor HDR mode (KDE Plasma SDR-on-HDR)")
                self.compositor_hdr_mode_checkbox.setChecked(bool(getattr(cfg, "compositor_hdr_mode", False)))
                self.sdr_boost_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.sdr_boost_nits_slider.setRange(SDR_BOOST_NITS_MIN, SDR_BOOST_NITS_MAX); self.sdr_boost_nits_slider.setValue(int(getattr(cfg, "sdr_boost_nits", 80.0)))
                self.sdr_boost_nits_value = QLabel("")
                self.motion_preset_combo = QComboBox(); self.motion_preset_combo.addItems(labels(MOTION_PRESET_LABELS)); self.motion_preset_combo.setCurrentIndex(max(0, self.motion_preset_combo.findText(label_for_value(MOTION_PRESET_LABELS, str(getattr(cfg, "motion_preset", "responsive")), default="Responsive"))))
                self.color_style_combo = QComboBox(); self.color_style_combo.addItems(labels(COLOR_STYLE_LABELS)); self.color_style_combo.setCurrentIndex(max(0, self.color_style_combo.findText(label_for_value(COLOR_STYLE_LABELS, str(getattr(cfg, "color_style", "natural")), default="Natural"))))
                self.edge_locality_combo = QComboBox(); self.edge_locality_combo.addItems(labels(EDGE_LOCALITY_LABELS)); self.edge_locality_combo.setCurrentIndex(max(0, self.edge_locality_combo.findText(label_for_value(EDGE_LOCALITY_LABELS, str(getattr(cfg, "edge_locality", "balanced")), default="Balanced"))))
                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens"); self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))

                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_count_slider.setRange(1, MAX_ZONE_COUNT); self.zone_count_slider.setValue(self._state.zone_count)
                self.layout_preset_combo = QComboBox(); self.layout_preset_combo.addItems(labels(LAYOUT_PRESET_LABELS)); self.layout_preset_combo.setCurrentIndex(max(0, self.layout_preset_combo.findText(label_for_value(LAYOUT_PRESET_LABELS, str(getattr(cfg, "layout_preset", "horizontal_debug" if self._state.zone_preset == "horizontal" else "edge_strip")), default="Edge strip"))))
                self.simple_calibration_widget = SimpleCalibrationWidget(qt=qt, title="Corner calibration")
                self.reverse_checkbox = self.simple_calibration_widget.reverse_orientation_checkbox; self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.device_zone_count_slider.setRange(1, self._device_zone_count_max()); self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.device_zone_count_status_label = QLabel("")
                self.strip_count_warning_label = QLabel("")
                self.assign_top_left_button = self.simple_calibration_widget.assign_top_left_button
                self.assign_top_right_button = self.simple_calibration_widget.assign_top_right_button
                self.assign_bottom_right_button = self.simple_calibration_widget.assign_bottom_right_button
                self.assign_bottom_left_button = self.simple_calibration_widget.assign_bottom_left_button
                self.reset_anchor_button = self.simple_calibration_widget.reset_anchors_button
                self.current_zone_label = self.simple_calibration_widget.current_zone_label
                self.test_step_index_label = self.simple_calibration_widget.step_index_label

                self.test_step_button = self.simple_calibration_widget.next_zone_button ; self.test_prev_button = self.simple_calibration_widget.prev_zone_button
                self._live_preview_timer = QTimer(self)
                live_single_shot = getattr(self._live_preview_timer, "setSingleShot", None)
                if callable(live_single_shot):
                    live_single_shot(True)
                self._live_preview_timer.timeout.connect(self._flush_live_preview)

                self.output_channel_order_combo = QComboBox(); self.output_channel_order_combo.addItems(["grb", "rgb", "rbg", "gbr", "brg", "bgr"]); self.output_channel_order_combo.setCurrentIndex(max(0, self.output_channel_order_combo.findText(str(getattr(cfg, "output_channel_order", "grb")))))
                self.device_model_combo = QComboBox()
                self.device_model_combo.addItems(["NL82K2 Lightstrip (PID 0x8202)", "NL82K1 Dock (PID 0x8201)", "Custom VID/PID"])
                self.device_vid_combo = QComboBox(); self.device_vid_combo.addItems(["0x37FA"])
                self.device_pid_combo = QComboBox(); self.device_pid_combo.addItems(["0x8202", "0x8201"])
                vid_hex = f"0x{int(getattr(cfg, 'device_vid', 0x37FA)):04X}"
                pid_hex = f"0x{int(getattr(cfg, 'device_pid', 0x8202)):04X}"
                if self.device_vid_combo.findText(vid_hex) < 0:
                    self.device_vid_combo.addItems([vid_hex])
                if self.device_pid_combo.findText(pid_hex) < 0:
                    self.device_pid_combo.addItems([pid_hex])
                self.device_vid_combo.setCurrentIndex(max(0, self.device_vid_combo.findText(vid_hex)))
                self.device_pid_combo.setCurrentIndex(max(0, self.device_pid_combo.findText(pid_hex)))
                if pid_hex == "0x8201":
                    self.device_model_combo.setCurrentIndex(1)
                elif pid_hex == "0x8202":
                    self.device_model_combo.setCurrentIndex(0)
                else:
                    self.device_model_combo.setCurrentIndex(2)
                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)"); self.mock_capture_checkbox.setChecked(bool(getattr(cfg, "use_mock_capture", False)))
                self.capture_backend_combo = QComboBox(); self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"]); self.capture_backend_combo.setCurrentIndex(max(0, self.capture_backend_combo.findText(str(getattr(cfg, "prefer_backend", "kwin-dbus")))))
                self.auto_probe_policy_combo = QComboBox(); self.auto_probe_policy_combo.addItems(["on-change", "first-run", "each-boot"]); self.auto_probe_policy_combo.setCurrentIndex(max(0, self.auto_probe_policy_combo.findText(str(getattr(cfg, "auto_probe_policy", "on-change")))))

                self.auto_latency_policy_combo = QComboBox(); self.auto_latency_policy_combo.addItems(["manual", "on-open", "on-open-once-per-backend"]); self.auto_latency_policy_combo.setCurrentIndex(max(0, self.auto_latency_policy_combo.findText(str(getattr(cfg, "auto_latency_policy", "manual")))))
                self.run_latency_button = QPushButton("Estimate frame interval")
                self.latency_label = QLabel(latency_result_summary(None))

                self.hdr_transfer_combo = QComboBox(); self.hdr_transfer_combo.addItems(["srgb", "pq"]); self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))))
                self.hdr_primaries_combo = QComboBox(); self.hdr_primaries_combo.addItems(["bt709", "bt2020"]); self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))))
                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.hdr_max_nits_slider.setRange(HDR_MAX_NITS_MIN, HDR_MAX_NITS_MAX); self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))
                self.sampling_quality_combo = QComboBox(); self.sampling_quality_combo.addItems(labels(SAMPLING_QUALITY_LABELS)); self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(label_for_value(SAMPLING_QUALITY_LABELS, str(getattr(cfg, "sampling_quality", "balanced")), default="Balanced"))))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.led_gamma_slider.setRange(100, 400); self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 1.0) * 100)))
                self.display_configurator_button = QPushButton("Re-run Display Setup"); self.display_configurator_button.clicked.connect(self._open_configurator)
                self.open_calibration_tool_button = QPushButton("Open calibration tool"); self.open_calibration_tool_button.clicked.connect(self._open_configurator)
                self._apply_tooltips()

                self.backend_info_label = QLabel("")
                self.diagnostics_mapping_label = QLabel("")
                self.preview_label = self.simple_calibration_widget.preview_text_label; self.preview_visual_label = self.simple_calibration_widget.preview_visual_label; self.test_label = QLabel("")
                self.brightness_value = QLabel(""); self.smoothing_value = QLabel(""); self.fps_value = QLabel(""); self.zone_count_value = QLabel(""); self.device_zone_count_value = QLabel(""); self.hdr_max_nits_value = QLabel(""); self.sdr_boost_nits_value = QLabel(""); self.sampling_quality_value = QLabel(""); self.smoothing_speed_value = QLabel(""); self.led_gamma_value = QLabel("")

                for signal in (
                    self.sampling_quality_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                    self.capture_backend_combo.currentIndexChanged,
                    self.auto_probe_policy_combo.currentIndexChanged,
                ):
                    signal.connect(self._refresh_preview_label)
                self.zone_count_slider.valueChanged.connect(self._on_zone_count_slider_changed)
                self.layout_preset_combo.currentIndexChanged.connect(self._on_zone_preset_changed)
                self.device_zone_count_slider.valueChanged.connect(self._on_device_zone_count_slider_changed)
                self._on_device_zone_count_slider_changed()
                self.simple_calibration_widget.bind_callbacks(
                    on_prev_zone=self._prev_test_zone,
                    on_next_zone=self._step_test_zone,
                    on_assign_top_left=lambda: self._assign_anchor("top_left"),
                    on_assign_top_right=lambda: self._assign_anchor("top_right"),
                    on_assign_bottom_right=lambda: self._assign_anchor("bottom_right"),
                    on_assign_bottom_left=lambda: self._assign_anchor("bottom_left"),
                    on_reset_anchors=self._reset_anchors,
                    on_reverse_orientation_changed=self._on_calibration_controls_changed,
                )
                self.run_latency_button.clicked.connect(self._run_latency_probe_manual)
                self.device_model_combo.currentIndexChanged.connect(self._sync_device_model_selection)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)

                root = QVBoxLayout()
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                self._settings_scroll = scroll
                content = QWidget()
                content_layout = QVBoxLayout()

                display_section = self._build_display_section(QGroupBox, QGridLayout, QLabel)
                runtime_section = self._build_runtime_section(QGroupBox, QGridLayout, QLabel)
                zone_mapping_section = self._build_zone_mapping_section(QGroupBox, QGridLayout, QLabel)
                calibration_section = self._build_calibration_testing_section(QGroupBox, QGridLayout, QLabel)
                output_section = self._build_output_startup_section(QGroupBox, QGridLayout, QLabel)
                diagnostics_section = self._build_backend_section(QGroupBox, QGridLayout, QLabel)

                self._section_widgets = {
                    "Display & Color": display_section,
                    "Performance": runtime_section,
                    "Edge Mapping": zone_mapping_section,
                    "Calibration": calibration_section,
                    "Device": output_section,
                    "Diagnostics": diagnostics_section,
                }
                content_layout.addWidget(display_section)
                content_layout.addWidget(runtime_section)
                content_layout.addWidget(zone_mapping_section)
                content_layout.addWidget(calibration_section)
                content_layout.addWidget(output_section)
                content_layout.addWidget(diagnostics_section)
                content_layout.addStretch(1)
                content.setLayout(content_layout)
                scroll.setWidget(content)
                root.addWidget(scroll)
                root.addWidget(buttons)
                self.setLayout(root)

                self._sync_device_model_selection()
                self._refresh_numeric_labels(); self._refresh_preview_label(); self._maybe_auto_run_latency_check()
                if initial_section:
                    self.focus_section(initial_section)

            def _apply_tooltips(self) -> None:
                self.brightness_slider.setToolTip("Overall output intensity. Lower values reduce LED brightness.")
                self.smoothing_slider.setToolTip("Blends frame-to-frame colors to reduce flicker.")
                self.smoothing_speed_slider.setToolTip("Motion response gain for smoothing. Lower values react slower (more smoothing); 0 keeps the strongest smoothing.")
                self.fps_slider.setToolTip("Capture/update target rate. Higher FPS uses more CPU/GPU.")
                self.sampling_quality_combo.setToolTip("Low = better performance, Balanced = default, High = best visual fidelity.")
                self.led_gamma_slider.setToolTip("Gamma correction for LED response. 1.00 keeps output linear.")
                self.zone_count_slider.setToolTip("Number of screen sampling zones sampled from the display.")
                self.reverse_checkbox.setToolTip("Flip strip direction if the mapping appears mirrored.")
                self.display_preset_combo.setToolTip("Select SDR, HDR, or Auto display behavior.")
                self.motion_preset_combo.setToolTip("Controls motion responsiveness.")
                self.color_style_combo.setToolTip("Controls color intensity style.")
                self.edge_locality_combo.setToolTip("Controls how close sampling stays to the edges.")
                self.hdr_max_nits_slider.setToolTip("Reference display peak brightness for HDR tone mapping.")
                self.capture_backend_combo.setToolTip("Select auto or force a specific capture backend.")
                self.device_model_combo.setToolTip("Select your Nanoleaf USB hardware model.")
                self.device_vid_combo.setToolTip("USB vendor ID used to locate your hardware.")
                self.device_pid_combo.setToolTip("USB product ID used to locate your hardware.")
                self.auto_probe_policy_combo.setToolTip("Choose when auto-backend probing should run.")
                self.auto_latency_policy_combo.setToolTip("Automatically run latency checks on selected lifecycle events.")
                self.device_zone_count_slider.setToolTip("Configured strip zone count used for device mapping.")
                self.output_channel_order_combo.setToolTip("Set RGB byte order expected by your strip controller.")
                self.mock_capture_checkbox.setToolTip("Use synthetic capture frames for diagnostics; USB output remains real hardware.")
                self.start_on_launch_checkbox.setToolTip("Start syncing automatically right after tray launch.")
                self.compositor_hdr_mode_checkbox.setToolTip("Enable compensation when KDE Plasma is running SDR content on HDR.")
                self.sdr_boost_nits_slider.setToolTip("Plasma SDR white reference in nits when compositor HDR mode is enabled.")

            def _build_backend_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Diagnostics")
                layout = QGridLayout()
                layout.addWidget(self.backend_info_label, 0, 0, 1, 3)
                layout.addWidget(QLabel("Capture backend policy"), 1, 0)
                layout.addWidget(self.capture_backend_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Auto-probe policy"), 2, 0)
                layout.addWidget(self.auto_probe_policy_combo, 2, 1, 1, 2)
                layout.addWidget(QLabel("Latency auto-run policy"), 3, 0)
                layout.addWidget(self.auto_latency_policy_combo, 3, 1, 1, 2)
                layout.addWidget(self.run_latency_button, 4, 0, 1, 2)
                layout.addWidget(self.latency_label, 5, 0, 1, 3)
                layout.addWidget(self.diagnostics_mapping_label, 6, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_display_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Display & Color")
                layout = QGridLayout()
                layout.addWidget(QLabel("Display mode"), 0, 0)
                layout.addWidget(self.display_preset_combo, 0, 1, 1, 2)
                layout.addWidget(QLabel("Motion"), 1, 0)
                layout.addWidget(self.motion_preset_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Color style"), 2, 0)
                layout.addWidget(self.color_style_combo, 2, 1, 1, 2)
                layout.addWidget(QLabel("Edge locality"), 3, 0)
                layout.addWidget(self.edge_locality_combo, 3, 1, 1, 2)
                hdr_advanced = QGroupBox("HDR advanced controls")
                hdr_advanced.setCheckable(True)
                hdr_advanced.setChecked(False)
                advanced_layout = QGridLayout()
                advanced_layout.addWidget(self.compositor_hdr_mode_checkbox, 0, 0, 1, 3)
                advanced_layout.addWidget(QLabel("SDR white reference"), 1, 0)
                advanced_layout.addWidget(self.sdr_boost_nits_slider, 1, 1)
                advanced_layout.addWidget(self.sdr_boost_nits_value, 1, 2)
                advanced_layout.addWidget(QLabel("HDR transfer"), 2, 0)
                advanced_layout.addWidget(self.hdr_transfer_combo, 2, 1, 1, 2)
                advanced_layout.addWidget(QLabel("HDR primaries"), 3, 0)
                advanced_layout.addWidget(self.hdr_primaries_combo, 3, 1, 1, 2)
                advanced_layout.addWidget(QLabel("HDR max brightness"), 4, 0)
                advanced_layout.addWidget(self.hdr_max_nits_slider, 4, 1)
                advanced_layout.addWidget(self.hdr_max_nits_value, 4, 2)
                hdr_advanced.setLayout(advanced_layout)
                layout.addWidget(hdr_advanced, 4, 0, 1, 3)
                layout.addWidget(self.display_configurator_button, 5, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_runtime_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Performance")
                layout = QGridLayout()
                layout.addWidget(QLabel("Brightness"), 0, 0); layout.addWidget(self.brightness_slider, 0, 1); layout.addWidget(self.brightness_value, 0, 2)
                layout.addWidget(QLabel("Smoothing"), 1, 0); layout.addWidget(self.smoothing_slider, 1, 1); layout.addWidget(self.smoothing_value, 1, 2)
                layout.addWidget(QLabel("Smoothing speed"), 2, 0); layout.addWidget(self.smoothing_speed_slider, 2, 1); layout.addWidget(self.smoothing_speed_value, 2, 2)
                layout.addWidget(QLabel("Capture FPS"), 3, 0); layout.addWidget(self.fps_slider, 3, 1); layout.addWidget(self.fps_value, 3, 2)
                layout.addWidget(QLabel("Quality"), 4, 0); layout.addWidget(self.sampling_quality_combo, 4, 1); layout.addWidget(self.sampling_quality_value, 4, 2)
                layout.addWidget(QLabel("Vibrancy (LED gamma)"), 5, 0); layout.addWidget(self.led_gamma_slider, 5, 1); layout.addWidget(self.led_gamma_value, 5, 2)
                group.setLayout(layout)
                return group

            def _build_zone_mapping_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Edge Mapping")
                layout = QGridLayout()
                layout.addWidget(QLabel("Screen sampling zone count"), 0, 0); layout.addWidget(self.zone_count_slider, 0, 1); layout.addWidget(self.zone_count_value, 0, 2)
                layout.addWidget(QLabel("Layout"), 1, 0); layout.addWidget(self.layout_preset_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Strip LED zone count"), 4, 0); layout.addWidget(self.device_zone_count_slider, 4, 1); layout.addWidget(self.device_zone_count_value, 4, 2)
                layout.addWidget(self.device_zone_count_status_label, 5, 0, 1, 3)
                layout.addWidget(self.strip_count_warning_label, 6, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_calibration_testing_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Calibration")
                layout = QGridLayout()
                layout.addWidget(QLabel("Use corner calibration to map the strip to your display corners."), 0, 0, 1, 3)
                layout.addWidget(self.open_calibration_tool_button, 1, 0, 1, 3)
                layout.addWidget(self.test_label, 2, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_output_startup_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Device")
                layout = QGridLayout()
                layout.addWidget(QLabel("Output channel order"), 0, 0); layout.addWidget(self.output_channel_order_combo, 0, 1, 1, 2)
                layout.addWidget(QLabel("Device model"), 1, 0); layout.addWidget(self.device_model_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Device VID"), 2, 0); layout.addWidget(self.device_vid_combo, 2, 1, 1, 2)
                layout.addWidget(QLabel("Device PID"), 3, 0); layout.addWidget(self.device_pid_combo, 3, 1, 1, 2)
                layout.addWidget(self.start_on_launch_checkbox, 4, 0, 1, 3)
                layout.addWidget(self.mock_capture_checkbox, 5, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _open_configurator(self): self._open_display_configurator = True; self.accept()
            def wants_display_configurator(self) -> bool: return bool(self._open_display_configurator)

            def _pull_state(self):
                layout_preset = value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_preset_combo.currentText()), default="edge_strip")
                self._state.zone_count = int(self.zone_count_slider.value()); self._state.zone_preset = "horizontal" if layout_preset == "horizontal_debug" else "edge-weighted"; self._state.reverse_zones = bool(self.reverse_checkbox.isChecked()); self._state.device_zone_count = int(self.device_zone_count_slider.value())
                self._state.calibration_model = "corner_anchored"

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

            def _refresh_numeric_labels(self):
                self.brightness_value.setText(f"{self.brightness_slider.value()}%"); self.smoothing_value.setText(f"{self.smoothing_slider.value()}%"); self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}"); self.fps_value.setText(f"{self.fps_slider.value()} fps"); self.sampling_quality_value.setText({"Low": "Better performance", "Balanced": "Default", "High": "Best visual fidelity"}.get(str(self.sampling_quality_combo.currentText()), "Default")); self.zone_count_value.setText(str(self.zone_count_slider.value())); self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits"); self.sdr_boost_nits_value.setText(f"{self.sdr_boost_nits_slider.value()} nits"); self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}")

            def _refresh_preview_label(self):
                self._refresh_numeric_labels(); self._pull_state()
                pending_cfg = replace(
                    cfg,
                    prefer_backend=str(self.capture_backend_combo.currentText()),
                    auto_probe_policy=str(self.auto_probe_policy_combo.currentText()),
                )
                preview_status = {
                    **self._runtime_status,
                    "requested_capture_backend": pending_cfg.prefer_backend,
                }
                info = backend_selection_info(preview_status, pending_cfg)
                self.backend_info_label.setText(
                    f"Requested backend policy: {info.requested_policy} | Selected backend: {info.selected_backend} "
                    f"| Effective runtime backend: {info.effective_backend} | Source: {info.source} | Reason: {info.reason}"
                    + (f" | Unresolved: {info.unresolved_reason}" if info.unresolved_reason else "")
                )

                self.device_zone_count_value.setText(str(self.device_zone_count_slider.value()))
                warnings: list[str] = []
                configured = int(self.device_zone_count_slider.value())
                detected = int(self._state.detected_device_zone_count or 0)
                source = int(self.zone_count_slider.value())
                anchor_max = max(
                    int(self._state.corner_anchor_top_left),
                    int(self._state.corner_anchor_top_right),
                    int(self._state.corner_anchor_bottom_right),
                    int(self._state.corner_anchor_bottom_left),
                )
                if detected > 0 and configured != detected:
                    warnings.append("Configured strip count differs from detected device count.")
                if source != configured:
                    warnings.append("Changing strip count may require recalibration.")
                if anchor_max >= configured:
                    warnings.append("Current anchors were assigned for a different strip length.")
                self.strip_count_warning_label.setText("\n".join(warnings))

                active_step = self._current_calibration_step()
                current_zone = active_step.device_zone_index
                step_total = self._test_cycle_length()
                self.current_zone_label.setText(
                    f"Test zone step: {self._test_step + 1}/{step_total} | Active physical strip zone: {current_zone}"
                )
                self.test_step_index_label.setText(f"{self._test_step + 1}/{step_total}")

                panel = build_testing_panel_state(
                    state=self._state,
                    runtime_status=preview_status,
                    cfg=pending_cfg,
                    mode=CALIBRATION_MODE_PHYSICAL,
                    step=self._test_step,
                )
                self.preview_label.setText(
                    f"{panel.zone_mode_summary}\nStrip LED zones in use: {panel.effective_zone_count}"
                )
                self.preview_visual_label.setText("")
                self.test_label.setText(f"{panel.active_test_description}\n{panel.backend_summary}")
                self.diagnostics_mapping_label.setText(
                    "\n".join(
                        (
                            f"Mapping preview: {self._state.mapping_preview_visual()}",
                            f"Raw device→source mapping: {self._state.mapping_preview_text()}",
                        )
                    )
                )

            def _sync_device_model_selection(self):
                selected_model = str(self.device_model_combo.currentText())
                if selected_model.startswith("NL82K2"):
                    vid_text = "0x37FA"
                    pid_text = "0x8202"
                elif selected_model.startswith("NL82K1"):
                    vid_text = "0x37FA"
                    pid_text = "0x8201"
                else:
                    return
                self.device_vid_combo.setCurrentIndex(max(0, self.device_vid_combo.findText(vid_text)))
                self.device_pid_combo.setCurrentIndex(max(0, self.device_pid_combo.findText(pid_text)))

            def _assign_anchor(self, corner: str):
                current_zone = self._current_calibration_step().device_zone_index
                if corner == "top_left":
                    self._state.corner_anchor_top_left = current_zone
                elif corner == "top_right":
                    self._state.corner_anchor_top_right = current_zone
                elif corner == "bottom_right":
                    self._state.corner_anchor_bottom_right = current_zone
                elif corner == "bottom_left":
                    self._state.corner_anchor_bottom_left = current_zone
                self._refresh_preview_label(); self._schedule_live_preview()

            def _reset_anchors(self):
                self._state.corner_anchor_top_left = -1
                self._state.corner_anchor_top_right = -1
                self._state.corner_anchor_bottom_right = -1
                self._state.corner_anchor_bottom_left = -1
                self._refresh_preview_label(); self._schedule_live_preview()

            def _current_calibration_step(self):
                self._test_step %= self._test_cycle_length()
                return self._state.step_for_mode(CALIBRATION_MODE_PHYSICAL, self._test_step)

            def _test_cycle_length(self): return self._state.cycle_length(CALIBRATION_MODE_PHYSICAL)
            def _step_test_zone(self): self._test_step = (self._test_step + 1) % self._test_cycle_length(); self._refresh_preview_label(); self._send_test_pattern()
            def _prev_test_zone(self): self._test_step = (self._test_step - 1) % self._test_cycle_length(); self._refresh_preview_label(); self._send_test_pattern()
            def _on_calibration_controls_changed(self): self._refresh_preview_label(); self._schedule_live_preview()

            def _schedule_live_preview(self):
                if self._calibration_sender is None:
                    return
                self._live_preview_timer.start(50)

            def _flush_live_preview(self):
                self._live_preview_timer.stop()
                self._send_test_pattern()

            def _send_test_pattern(self):
                if self._calibration_sender is None: return
                self._pull_state()
                # Normalize self._test_step before generating the frame.
                self._current_calibration_step()
                colors = self._state.frame_for_step(mode=CALIBRATION_MODE_PHYSICAL, step=self._test_step, brightness=1.0, all_off_except_active=True)
                self._calibration_sender(colors)

            def _device_zone_count_max(self) -> int:
                detected = int(self._state.detected_device_zone_count)
                if detected > 0:
                    return max(1, detected)
                return MAX_ZONE_COUNT

            def _on_device_zone_count_slider_changed(self, *_args) -> None:
                previous_zone_count = self._state.effective_device_zone_count()
                max_count = self._device_zone_count_max()
                requested = int(self.device_zone_count_slider.value())
                clamped = max(1, min(requested, max_count))
                if requested != clamped:
                    self._set_slider_value_safely(self.device_zone_count_slider, clamped)
                    self.device_zone_count_status_label.setText(
                        f"Strip LED zone count capped at detected hardware count ({max_count})."
                    )
                else:
                    self.device_zone_count_status_label.setText("")
                if self._source_zones_locked_to_device_count:
                    self._set_slider_value_safely(self.zone_count_slider, clamped)
                self._test_step %= max(1, clamped)
                self._refresh_preview_label()

            def _on_zone_count_slider_changed(self, *_args) -> None:
                self._source_zones_locked_to_device_count = False
                self._state.source_zones_user_configured = True
                self._refresh_preview_label()

            def _on_zone_preset_changed(self, *_args) -> None:
                if value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_preset_combo.currentText()), default="edge_strip") != "edge_strip":
                    self._source_zones_locked_to_device_count = False
                self._refresh_preview_label()

            def _active_backend(self) -> str:
                preview_status = {
                    **(runtime_status or {}),
                    "requested_capture_backend": str(self.capture_backend_combo.currentText()),
                }
                info = backend_selection_info(preview_status, cfg)
                if info.effective_backend in {"not-started", "unresolved"}:
                    return info.selected_backend
                return info.effective_backend

            def _run_latency_probe_manual(self):
                info = backend_selection_info(self._runtime_status, cfg)
                measured = self._measured_latency_from_runtime(triggered_by="manual")
                if measured is not None:
                    self._latest_latency = build_latency_result(
                        requested_policy=info.requested_policy,
                        selected_backend=self._active_backend(),
                        selection_source=info.source,
                        selection_reason=info.reason,
                        measured_latency_ms=measured["latency_ms"],
                        measurement_kind="measured",
                        confidence_note=measured["confidence_note"],
                        triggered_by="manual",
                        details=measured["details"],
                    )
                    self.run_latency_button.setText("Measure frame interval")
                else:
                    self._latest_latency = build_latency_result(requested_policy=info.requested_policy, selected_backend=self._active_backend(), selection_source=info.source, selection_reason=info.reason, measured_latency_ms=1000.0 / max(1, int(self.fps_slider.value())), measurement_kind="estimated", confidence_note="Frame-interval estimate from configured FPS; not a hardware timing sample", triggered_by="manual", details="Manual latency estimate")
                    self.run_latency_button.setText("Estimate frame interval")
                self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _maybe_auto_run_latency_check(self):
                if should_auto_run_latency_probe(policy=str(self.auto_latency_policy_combo.currentText()), last_result=self._latest_latency, active_backend=self._active_backend()):
                    info = backend_selection_info(self._runtime_status, cfg)
                    measured = self._measured_latency_from_runtime(triggered_by="auto")
                    if measured is not None:
                        self._latest_latency = build_latency_result(
                            requested_policy=info.requested_policy,
                            selected_backend=self._active_backend(),
                            selection_source=info.source,
                            selection_reason=info.reason,
                            measured_latency_ms=measured["latency_ms"],
                            measurement_kind="measured",
                            confidence_note=measured["confidence_note"],
                            triggered_by="auto",
                            details=measured["details"],
                        )
                        self.run_latency_button.setText("Measure frame interval")
                    else:
                        self._latest_latency = build_latency_result(requested_policy=info.requested_policy, selected_backend=self._active_backend(), selection_source=info.source, selection_reason=info.reason, measured_latency_ms=1000.0 / max(1, int(self.fps_slider.value())), measurement_kind="estimated", confidence_note="Derived from configured FPS; auto-run estimate", triggered_by="auto", details="Auto-run on settings open")
                        self.run_latency_button.setText("Estimate frame interval")
                    self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _measured_latency_from_runtime(self, *, triggered_by: str) -> dict[str, object] | None:
                measurement = self._runtime_status.get("latency_measurement")
                if not isinstance(measurement, dict):
                    return None
                sample_count = int(measurement.get("sample_count") or 0)
                if sample_count <= 0:
                    return None
                pipeline_median = float(measurement.get("pipeline_median_ms") or 0.0)
                pipeline_p95 = float(measurement.get("pipeline_p95_ms") or 0.0)
                cadence_median = float(measurement.get("capture_interval_median_ms") or 0.0)
                cadence_p95 = float(measurement.get("capture_interval_p95_ms") or 0.0)
                jitter = float(measurement.get("pipeline_jitter_ms") or 0.0)
                return {
                    "latency_ms": pipeline_median,
                    "confidence_note": (
                        f"Measured runtime samples (n={sample_count}, median={pipeline_median:.1f}ms, p95={pipeline_p95:.1f}ms, jitter={jitter:.1f}ms)"
                    ),
                    "details": (
                        f"{'Manual' if triggered_by == 'manual' else 'Auto'} measured runtime latency | "
                        f"cadence median/p95={cadence_median:.1f}/{cadence_p95:.1f}ms | "
                        f"pipeline median/p95={pipeline_median:.1f}/{pipeline_p95:.1f}ms | "
                        f"jitter={jitter:.1f}ms | samples={sample_count}"
                    ),
                }

            def focus_section(self, section_name: str) -> bool:
                target = self._section_widgets.get(section_name)
                if target is None:
                    return False
                scroll = self._settings_scroll
                if scroll is None:
                    return False
                ensure_widget_visible = getattr(scroll, "ensureWidgetVisible", None)
                if callable(ensure_widget_visible):
                    ensure_widget_visible(target, 0, 40)
                    return True
                return False

            def updated_config(self) -> AppConfig:
                self._pull_state()
                selected_model = str(self.device_model_combo.currentText())
                if selected_model.startswith("NL82K2"):
                    vid_value = 0x37FA
                    pid_value = 0x8202
                elif selected_model.startswith("NL82K1"):
                    vid_value = 0x37FA
                    pid_value = 0x8201
                else:
                    vid_value = int(str(self.device_vid_combo.currentText()), 0)
                    pid_value = int(str(self.device_pid_combo.currentText()), 0)
                new_zones = make_edge_weighted_zones(self._state.zone_count) if self._state.zone_preset == "edge-weighted" else make_horizontal_zones(self._state.zone_count)
                calibration_schema_version = int(getattr(cfg, "calibration_schema_version", 1) or 1)
                calibration_payload = CalibrationConfig(
                    schema_version=calibration_schema_version,
                    calibration_schema_version=calibration_schema_version,
                    calibration_model="corner_anchored",
                    device_zone_count=int(self._state.device_zone_count),
                    output_channel_order=str(self.output_channel_order_combo.currentText()),
                    reverse_zones=bool(self._state.reverse_zones),
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map],
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                )
                return replace(
                    cfg,
                    fps=int(self.fps_slider.value()), sampling_quality=str(self.sampling_quality_combo.currentText()).lower(), brightness=self.brightness_slider.value() / 100.0,
                    smoothing=self.smoothing_slider.value() / 100.0, smoothing_speed=self.smoothing_speed_slider.value() / 100.0, led_gamma=self.led_gamma_slider.value() / 100.0,
                    zones=new_zones, zone_preset=self._state.zone_preset, layout_preset=value_for_label(LAYOUT_PRESET_LABELS, str(self.layout_preset_combo.currentText()), default="edge_strip"), edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="balanced"), motion_preset=value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"), color_style=value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="natural"), display_preset=value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="sdr"), color_mode=("dynamic" if value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive") == "dynamic" else "balanced"), hdr_enabled=value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="sdr") in {"hdr", "auto"},
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()), device_zone_count=self._state.device_zone_count,
                    output_channel_order=str(self.output_channel_order_combo.currentText()), reverse_zones=self._state.reverse_zones,
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map] if self._state.manual_mapping_enabled else [],
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    use_mock_capture=bool(self.mock_capture_checkbox.isChecked()), prefer_backend=str(self.capture_backend_combo.currentText()), auto_probe_policy=str(self.auto_probe_policy_combo.currentText()), auto_latency_policy=str(self.auto_latency_policy_combo.currentText()),
                    latency_last_backend=(self._latest_latency.selected_backend if self._latest_latency else getattr(cfg, "latency_last_backend", "")),
                    latency_last_value_ms=(self._latest_latency.measured_latency_ms if self._latest_latency else float(getattr(cfg, "latency_last_value_ms", 0.0))),
                    latency_last_trigger=(self._latest_latency.triggered_by if self._latest_latency else getattr(cfg, "latency_last_trigger", "")),
                    latency_last_timestamp=(self._latest_latency.recorded_at_utc if self._latest_latency else getattr(cfg, "latency_last_timestamp", "")),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()), hdr_primaries=str(self.hdr_primaries_combo.currentText()), hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    compositor_hdr_mode=bool(self.compositor_hdr_mode_checkbox.isChecked()), sdr_boost_nits=float(self.sdr_boost_nits_slider.value()),
                    device_vid=int(vid_value), device_pid=int(pid_value),
                    calibration_schema_version=calibration_schema_version,
                    calibration_model="corner_anchored",
                    calibration=calibration_payload,
                )

        self._dialog = _Dialog()

    def exec(self) -> int: return self._dialog.exec()
    def updated_config(self) -> AppConfig: return self._dialog.updated_config()
    def wants_display_configurator(self) -> bool: return bool(self._dialog.wants_display_configurator())
    def focus_section(self, section_name: str) -> bool: return bool(self._dialog.focus_section(section_name))
