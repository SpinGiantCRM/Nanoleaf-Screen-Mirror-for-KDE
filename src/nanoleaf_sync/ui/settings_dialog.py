from __future__ import annotations

from dataclasses import replace
from typing import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import calibration_sequence_text
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    backend_selection_info,
    build_latency_result,
    latency_result_summary,
    next_corner_start_anchor,
    should_auto_run_latency_probe,
    build_testing_panel_state,
)
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text as _mapping_preview_text
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

FPS_MIN = 1
FPS_MAX = 120
HDR_MAX_NITS_MIN = 80
HDR_MAX_NITS_MAX = 10000
SAMPLING_QUALITY_OPTIONS: tuple[str, ...] = ("Low", "Balanced", "High")
MAX_ZONE_COUNT = 128
SDR_BOOST_NITS_MIN = 80
SDR_BOOST_NITS_MAX = 400
CALIBRATION_MODE_CORNER = "corner+offset alignment"

SETTINGS_SECTIONS: tuple[str, ...] = (
    "Backend & Diagnostics",
    "Display & Color",
    "Runtime & Performance",
    "Zone Mapping",
    "Calibration & Testing",
    "Output & Startup",
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
                self._test_step = 0
                self._latest_latency = None
                self._section_widgets: dict[str, object] = {}
                self._settings_scroll = None

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.brightness_slider.setRange(0, 100); self.brightness_slider.setValue(int(round(cfg.brightness * 100)))
                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_slider.setRange(0, 100); self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))
                self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_speed_slider.setRange(0, 400); self.smoothing_speed_slider.setValue(int(round(getattr(cfg, "smoothing_speed", 0.75) * 100)))
                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.fps_slider.setRange(FPS_MIN, FPS_MAX); self.fps_slider.setValue(int(cfg.fps))
                self.display_mode_combo = QComboBox(); self.display_mode_combo.addItems(["sdr", "hdr"]); self.display_mode_combo.setCurrentIndex(1 if cfg.hdr_enabled else 0)
                self.compositor_hdr_mode_checkbox = QCheckBox("Compositor HDR mode (KDE Plasma SDR-on-HDR)")
                self.compositor_hdr_mode_checkbox.setChecked(bool(getattr(cfg, "compositor_hdr_mode", False)))
                self.sdr_boost_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.sdr_boost_nits_slider.setRange(SDR_BOOST_NITS_MIN, SDR_BOOST_NITS_MAX); self.sdr_boost_nits_slider.setValue(int(getattr(cfg, "sdr_boost_nits", 80.0)))
                self.sdr_boost_nits_value = QLabel("")
                self.color_mode_combo = QComboBox(); self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"]); self.color_mode_combo.setCurrentIndex(max(0, self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))))
                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens"); self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))

                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_count_slider.setRange(1, MAX_ZONE_COUNT); self.zone_count_slider.setValue(self._state.zone_count)
                self.zone_preset_combo = QComboBox(); self.zone_preset_combo.addItems(["Edge strip (recommended)", "Full-screen horizontal"]); self.zone_preset_combo.setCurrentIndex(0 if self._state.zone_preset == "edge-weighted" else 1)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal); initial_offset_limit = max(1, self._state.effective_device_zone_count() - 1); self.zone_offset_slider.setRange(-initial_offset_limit, initial_offset_limit); self.zone_offset_slider.setValue(self._state.zone_offset)
                self.reverse_checkbox = QCheckBox("Reverse strip orientation"); self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.device_zone_count_slider.setRange(1, MAX_ZONE_COUNT); self.device_zone_count_slider.setValue(self._state.device_zone_count)
                self.corner_anchor_button = QPushButton("Set next top-left anchor")
                self.assign_top_left_button = QPushButton("Assign current zone → Top-left")
                self.assign_top_right_button = QPushButton("Assign current zone → Top-right")
                self.assign_bottom_right_button = QPushButton("Assign current zone → Bottom-right")
                self.assign_bottom_left_button = QPushButton("Assign current zone → Bottom-left")
                self.reset_anchor_button = QPushButton("Reset corner anchors")
                self.current_zone_label = QLabel("")
                self.test_step_index_label = QLabel("")

                self.test_step_button = QPushButton("Next test zone step") ; self.test_prev_button = QPushButton("Previous test zone step")
                self.test_mode_combo = QComboBox(); self.test_mode_combo.addItems([CALIBRATION_MODE_CORNER])
                mode_set_enabled = getattr(self.test_mode_combo, "setEnabled", None)
                if callable(mode_set_enabled):
                    mode_set_enabled(False)
                self.test_auto_checkbox = QCheckBox("Auto-step")
                self.test_loop_checkbox = QCheckBox("Loop"); self.test_loop_checkbox.setChecked(True)
                self.test_duration_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_duration_slider.setRange(1, 60); self.test_duration_slider.setValue(12)
                self.test_step_interval_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_step_interval_slider.setRange(100, 2000); self.test_step_interval_slider.setValue(500)
                self.test_brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.test_brightness_slider.setRange(5, 100); self.test_brightness_slider.setValue(100)
                self.test_background_checkbox = QCheckBox("All off except active zone"); self.test_background_checkbox.setChecked(True)
                self._test_elapsed_ms = 0
                self._test_timer = QTimer(self); self._test_timer.timeout.connect(self._on_test_timer_tick)
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
                self.sampling_quality_combo = QComboBox(); self.sampling_quality_combo.addItems(list(SAMPLING_QUALITY_OPTIONS)); self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(str(getattr(cfg, "sampling_quality", "balanced")).capitalize())))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.led_gamma_slider.setRange(100, 400); self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 1.0) * 100)))
                self.display_configurator_button = QPushButton("Re-run Display Setup"); self.display_configurator_button.clicked.connect(self._open_configurator)
                self._apply_tooltips()

                self.backend_info_label = QLabel("")
                self.preview_label = QLabel(""); self.preview_visual_label = QLabel(""); self.test_label = QLabel("")
                self.brightness_value = QLabel(""); self.smoothing_value = QLabel(""); self.fps_value = QLabel(""); self.zone_count_value = QLabel(""); self.zone_offset_value = QLabel(""); self.device_zone_count_value = QLabel(""); self.hdr_max_nits_value = QLabel(""); self.sdr_boost_nits_value = QLabel(""); self.sampling_quality_value = QLabel(""); self.smoothing_speed_value = QLabel(""); self.led_gamma_value = QLabel(""); self.test_duration_value = QLabel(""); self.test_step_interval_value = QLabel(""); self.test_brightness_value = QLabel("")

                for signal in (
                    self.zone_count_slider.valueChanged,
                    self.sampling_quality_combo.currentIndexChanged,
                    self.zone_preset_combo.currentIndexChanged,
                    self.zone_offset_slider.valueChanged,
                    self.device_zone_count_slider.valueChanged,
                    self.reverse_checkbox.stateChanged,
                    self.capture_backend_combo.currentIndexChanged,
                    self.auto_probe_policy_combo.currentIndexChanged,
                ):
                    signal.connect(self._refresh_preview_label)
                self.corner_anchor_button.clicked.connect(self._rotate_anchor)
                self.assign_top_left_button.clicked.connect(lambda: self._assign_anchor("top_left"))
                self.assign_top_right_button.clicked.connect(lambda: self._assign_anchor("top_right"))
                self.assign_bottom_right_button.clicked.connect(lambda: self._assign_anchor("bottom_right"))
                self.assign_bottom_left_button.clicked.connect(lambda: self._assign_anchor("bottom_left"))
                self.reset_anchor_button.clicked.connect(self._reset_anchors)
                self.test_step_button.clicked.connect(self._step_test_zone); self.test_prev_button.clicked.connect(self._prev_test_zone)
                self.test_auto_checkbox.stateChanged.connect(self._on_test_auto_toggled); self.test_mode_combo.currentIndexChanged.connect(self._on_calibration_controls_changed)
                self.test_step_interval_slider.valueChanged.connect(self._on_interval_changed)
                self.test_brightness_slider.valueChanged.connect(self._on_calibration_controls_changed)
                self.test_background_checkbox.stateChanged.connect(self._on_calibration_controls_changed)
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

                backend_section = self._build_backend_section(QGroupBox, QGridLayout, QLabel)
                display_section = self._build_display_section(QGroupBox, QGridLayout, QLabel)
                runtime_section = self._build_runtime_section(QGroupBox, QGridLayout, QLabel)
                zone_mapping_section = self._build_zone_mapping_section(QGroupBox, QGridLayout, QLabel)
                calibration_section = self._build_calibration_testing_section(QGroupBox, QGridLayout, QLabel)
                output_section = self._build_output_startup_section(QGroupBox, QGridLayout, QLabel)

                self._section_widgets = {
                    "Backend & Diagnostics": backend_section,
                    "Display & Color": display_section,
                    "Runtime & Performance": runtime_section,
                    "Zone Mapping": zone_mapping_section,
                    "Calibration & Testing": calibration_section,
                    "Output & Startup": output_section,
                }
                content_layout.addWidget(backend_section)
                content_layout.addWidget(display_section)
                content_layout.addWidget(runtime_section)
                content_layout.addWidget(zone_mapping_section)
                content_layout.addWidget(calibration_section)
                content_layout.addWidget(output_section)
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
                self.zone_offset_slider.setToolTip("Global mapping zone offset that rotates the strip mapping around strip LED zones.")
                self.reverse_checkbox.setToolTip("Flip strip direction if the mapping appears mirrored.")
                self.display_mode_combo.setToolTip("Select SDR or HDR processing mode.")
                self.color_mode_combo.setToolTip("Colour behavior preset used by the analyzer.")
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
                group = QGroupBox("Backend & Diagnostics")
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
                group.setLayout(layout)
                return group

            def _build_display_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Display & Color")
                layout = QGridLayout()
                layout.addWidget(QLabel("SDR/HDR mode"), 0, 0)
                layout.addWidget(self.display_mode_combo, 0, 1, 1, 2)
                layout.addWidget(QLabel("Colour behavior preset"), 1, 0)
                layout.addWidget(self.color_mode_combo, 1, 1, 1, 2)
                layout.addWidget(self.compositor_hdr_mode_checkbox, 2, 0, 1, 3)
                layout.addWidget(QLabel("SDR white reference"), 3, 0)
                layout.addWidget(self.sdr_boost_nits_slider, 3, 1)
                layout.addWidget(self.sdr_boost_nits_value, 3, 2)
                layout.addWidget(QLabel("HDR transfer"), 4, 0)
                layout.addWidget(self.hdr_transfer_combo, 4, 1, 1, 2)
                layout.addWidget(QLabel("HDR primaries"), 5, 0)
                layout.addWidget(self.hdr_primaries_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("HDR max brightness"), 6, 0)
                layout.addWidget(self.hdr_max_nits_slider, 6, 1)
                layout.addWidget(self.hdr_max_nits_value, 6, 2)
                layout.addWidget(self.display_configurator_button, 7, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_runtime_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Runtime & Performance")
                layout = QGridLayout()
                layout.addWidget(QLabel("Brightness"), 0, 0); layout.addWidget(self.brightness_slider, 0, 1); layout.addWidget(self.brightness_value, 0, 2)
                layout.addWidget(QLabel("Smoothing"), 1, 0); layout.addWidget(self.smoothing_slider, 1, 1); layout.addWidget(self.smoothing_value, 1, 2)
                layout.addWidget(QLabel("Smoothing speed"), 2, 0); layout.addWidget(self.smoothing_speed_slider, 2, 1); layout.addWidget(self.smoothing_speed_value, 2, 2)
                layout.addWidget(QLabel("Capture FPS"), 3, 0); layout.addWidget(self.fps_slider, 3, 1); layout.addWidget(self.fps_value, 3, 2)
                layout.addWidget(QLabel("Sampling quality"), 4, 0); layout.addWidget(self.sampling_quality_combo, 4, 1); layout.addWidget(self.sampling_quality_value, 4, 2)
                layout.addWidget(QLabel("LED gamma"), 5, 0); layout.addWidget(self.led_gamma_slider, 5, 1); layout.addWidget(self.led_gamma_value, 5, 2)
                group.setLayout(layout)
                return group

            def _build_zone_mapping_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Zone Mapping")
                layout = QGridLayout()
                layout.addWidget(QLabel("Screen sampling zone count"), 0, 0); layout.addWidget(self.zone_count_slider, 0, 1); layout.addWidget(self.zone_count_value, 0, 2)
                layout.addWidget(QLabel("Zone layout preset"), 1, 0); layout.addWidget(self.zone_preset_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Global mapping zone offset (rotation)"), 2, 0); layout.addWidget(self.zone_offset_slider, 2, 1); layout.addWidget(self.zone_offset_value, 2, 2)
                layout.addWidget(self.reverse_checkbox, 3, 0, 1, 2)
                layout.addWidget(QLabel("Strip LED zone count"), 4, 0); layout.addWidget(self.device_zone_count_slider, 4, 1); layout.addWidget(self.device_zone_count_value, 4, 2)
                row = 5
                layout.addWidget(self.current_zone_label, row, 0, 1, 3)
                layout.addWidget(self.assign_top_left_button, row + 1, 0, 1, 3)
                layout.addWidget(self.assign_top_right_button, row + 2, 0, 1, 3)
                layout.addWidget(self.assign_bottom_right_button, row + 3, 0, 1, 3)
                layout.addWidget(self.assign_bottom_left_button, row + 4, 0, 1, 3)
                layout.addWidget(self.reset_anchor_button, row + 5, 0, 1, 3)
                layout.addWidget(self.corner_anchor_button, row + 6, 0, 1, 2)
                layout.addWidget(self.preview_label, row + 7, 0, 1, 3)
                layout.addWidget(self.preview_visual_label, row + 8, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_calibration_testing_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Calibration & Testing")
                layout = QGridLayout()
                layout.addWidget(QLabel(f"Calibration sequence:\n{calibration_sequence_text()}"), 0, 0, 1, 3)
                layout.addWidget(QLabel("Test mode"), 1, 0); layout.addWidget(self.test_mode_combo, 1, 1, 1, 2)
                layout.addWidget(self.test_step_button, 2, 0, 1, 2); layout.addWidget(self.test_prev_button, 2, 2)
                layout.addWidget(QLabel("Test zone step index"), 3, 0); layout.addWidget(self.test_step_index_label, 3, 1, 1, 2)
                layout.addWidget(self.test_auto_checkbox, 4, 0); layout.addWidget(self.test_loop_checkbox, 4, 1)
                layout.addWidget(QLabel("Test duration (s)"), 5, 0); layout.addWidget(self.test_duration_slider, 5, 1); layout.addWidget(self.test_duration_value, 5, 2)
                layout.addWidget(QLabel("Test step interval (ms)"), 6, 0); layout.addWidget(self.test_step_interval_slider, 6, 1); layout.addWidget(self.test_step_interval_value, 6, 2)
                layout.addWidget(QLabel("Test brightness"), 7, 0); layout.addWidget(self.test_brightness_slider, 7, 1); layout.addWidget(self.test_brightness_value, 7, 2)
                layout.addWidget(self.test_background_checkbox, 8, 0, 1, 2)
                layout.addWidget(QLabel("Live preview: mapping changes are sent automatically."), 9, 0, 1, 3)
                layout.addWidget(self.test_label, 10, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_output_startup_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Output & Startup")
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
                zone_preset_label = str(self.zone_preset_combo.currentText())
                self._state.zone_count = int(self.zone_count_slider.value()); self._state.zone_preset = "edge-weighted" if zone_preset_label.startswith("Edge strip") else "horizontal"; self._state.zone_offset = int(self.zone_offset_slider.value()); self._state.reverse_zones = bool(self.reverse_checkbox.isChecked()); self._state.device_zone_count = int(self.device_zone_count_slider.value())

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
                preserved_position = int(offset) % previous_total
                return self._normalize_offset_for_count(preserved_position, new_total)

            def _set_slider_value_safely(self, slider, value: int) -> None:
                block_signals = getattr(slider, "blockSignals", None)
                previous = False
                if callable(block_signals):
                    previous = bool(block_signals(True))
                slider.setValue(int(value))
                if callable(block_signals):
                    block_signals(previous)

            def _sync_zone_offset_slider(self, previous_zone_count: int | None = None) -> None:
                current_zone_count = max(1, int(self.device_zone_count_slider.value()))
                old_zone_count = max(1, int(previous_zone_count or current_zone_count))
                remapped_offset = self._remap_offset_between_counts(
                    int(self.zone_offset_slider.value()),
                    old_zone_count,
                    current_zone_count,
                )
                offset_limit = max(1, current_zone_count - 1)
                self.zone_offset_slider.setRange(-offset_limit, offset_limit)
                self._set_slider_value_safely(self.zone_offset_slider, remapped_offset)

            def _refresh_numeric_labels(self):
                normalized_offset = self._normalize_offset_for_count(
                    int(self.zone_offset_slider.value()),
                    max(1, int(self.device_zone_count_slider.value())),
                )
                self.brightness_value.setText(f"{self.brightness_slider.value()}%"); self.smoothing_value.setText(f"{self.smoothing_slider.value()}%"); self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}"); self.fps_value.setText(f"{self.fps_slider.value()} fps"); self.sampling_quality_value.setText({"Low": "Better performance", "Balanced": "Default", "High": "Best visual fidelity"}.get(str(self.sampling_quality_combo.currentText()), "Default")); self.zone_count_value.setText(str(self.zone_count_slider.value())); self.zone_offset_value.setText(f"{normalized_offset:+d} (raw {int(self.zone_offset_slider.value()):+d})"); self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits"); self.sdr_boost_nits_value.setText(f"{self.sdr_boost_nits_slider.value()} nits"); self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}"); self.test_duration_value.setText(str(self.test_duration_slider.value())); self.test_step_interval_value.setText(str(self.test_step_interval_slider.value())); self.test_brightness_value.setText(f"{self.test_brightness_slider.value()}%")

            def _refresh_preview_label(self):
                self._sync_zone_offset_slider(previous_zone_count=self._state.effective_device_zone_count())
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

                active_step = self._current_calibration_step()
                current_zone = active_step.device_zone_index
                step_total = self._test_cycle_length()
                self.current_zone_label.setText(
                    f"Test zone step: {self._test_step + 1}/{step_total} | Active physical strip zone: {current_zone} | Normalized offset: {self._normalize_offset_for_count(self._state.zone_offset, self._state.effective_device_zone_count()):+d}"
                )
                self.test_step_index_label.setText(f"{self._test_step + 1}/{step_total}")

                panel = build_testing_panel_state(
                    state=self._state,
                    runtime_status=preview_status,
                    cfg=pending_cfg,
                    mode=CALIBRATION_MODE_CORNER,
                    step=self._test_step,
                )
                self.preview_label.setText(
                    f"{panel.zone_mode_summary}\nEffective strip LED zone count in use: {panel.effective_zone_count}\n{self._state.mapping_preview_text()}"
                )
                self.preview_visual_label.setText(self._state.mapping_preview_visual())
                self.test_label.setText(f"{panel.active_test_description}\n{panel.backend_summary}")

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

            def _rotate_anchor(self):
                self._pull_state(); self._state.corner_start_anchor = next_corner_start_anchor(self._state.corner_start_anchor, device_zone_count=self._state.effective_device_zone_count()); self._refresh_preview_label(); self._schedule_live_preview()


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
                return self._state.step_for_mode(CALIBRATION_MODE_CORNER, self._test_step)

            def _test_cycle_length(self): return self._state.cycle_length(CALIBRATION_MODE_CORNER)
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
                self._current_calibration_step()
                colors = self._state.frame_for_step(mode=CALIBRATION_MODE_CORNER, step=self._test_step, brightness=self.test_brightness_slider.value()/100.0, all_off_except_active=bool(self.test_background_checkbox.isChecked()))
                self._calibration_sender(colors)

            def _on_test_auto_toggled(self):
                self._test_elapsed_ms = 0
                if self.test_auto_checkbox.isChecked(): self._test_timer.start(max(100, int(self.test_step_interval_slider.value())))
                else: self._test_timer.stop()
                self._schedule_live_preview()

            def _on_test_timer_tick(self):
                self._test_elapsed_ms += max(100, int(self.test_step_interval_slider.value()))
                if self._test_elapsed_ms >= int(self.test_duration_slider.value()) * 1000:
                    if self.test_loop_checkbox.isChecked(): self._test_elapsed_ms = 0; self._test_step = 0
                    else: self.test_auto_checkbox.setChecked(False); self._test_timer.stop(); return
                self._step_test_zone()

            def _on_interval_changed(self):
                if self._test_timer.isActive(): self._test_timer.setInterval(max(100, int(self.test_step_interval_slider.value())))

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
                return replace(
                    cfg,
                    fps=int(self.fps_slider.value()), sampling_quality=str(self.sampling_quality_combo.currentText()).lower(), brightness=self.brightness_slider.value() / 100.0,
                    smoothing=self.smoothing_slider.value() / 100.0, smoothing_speed=self.smoothing_speed_slider.value() / 100.0, led_gamma=self.led_gamma_slider.value() / 100.0,
                    zones=new_zones, zone_preset=self._state.zone_preset, color_mode=str(self.color_mode_combo.currentText()), hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()), device_zone_count=self._state.device_zone_count,
                    output_channel_order=str(self.output_channel_order_combo.currentText()), zone_offset=self._state.zone_offset, reverse_zones=self._state.reverse_zones,
                    manual_mapping_enabled=bool(self._state.manual_mapping_enabled),
                    explicit_zone_map=[int(i) for i in self._state.explicit_zone_map] if self._state.manual_mapping_enabled else [],
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    corner_start_anchor=int(self._state.corner_start_anchor), use_mock_capture=bool(self.mock_capture_checkbox.isChecked()), prefer_backend=str(self.capture_backend_combo.currentText()), auto_probe_policy=str(self.auto_probe_policy_combo.currentText()), auto_latency_policy=str(self.auto_latency_policy_combo.currentText()),
                    corner_offsets_enabled=bool(self._state.corner_offsets_enabled),
                    corner_zone_offsets=self._state.active_corner_zone_offsets(),
                    latency_last_backend=(self._latest_latency.selected_backend if self._latest_latency else getattr(cfg, "latency_last_backend", "")),
                    latency_last_value_ms=(self._latest_latency.measured_latency_ms if self._latest_latency else float(getattr(cfg, "latency_last_value_ms", 0.0))),
                    latency_last_trigger=(self._latest_latency.triggered_by if self._latest_latency else getattr(cfg, "latency_last_trigger", "")),
                    latency_last_timestamp=(self._latest_latency.recorded_at_utc if self._latest_latency else getattr(cfg, "latency_last_timestamp", "")),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()), hdr_primaries=str(self.hdr_primaries_combo.currentText()), hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    compositor_hdr_mode=bool(self.compositor_hdr_mode_checkbox.isChecked()), sdr_boost_nits=float(self.sdr_boost_nits_slider.value()),
                    device_vid=int(vid_value), device_pid=int(pid_value),
                )

        self._dialog = _Dialog()

    def exec(self) -> int: return self._dialog.exec()
    def updated_config(self) -> AppConfig: return self._dialog.updated_config()
    def wants_display_configurator(self) -> bool: return bool(self._dialog.wants_display_configurator())
    def focus_section(self, section_name: str) -> bool: return bool(self._dialog.focus_section(section_name))
