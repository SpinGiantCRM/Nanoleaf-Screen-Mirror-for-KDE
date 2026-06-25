"""Main settings dialog widget shell and wiring."""

from __future__ import annotations

import copy

from nanoleaf_sync.config.model import (
    AppConfig,
    LedCalibrationProfile,
)
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    latency_result_summary,
)
from nanoleaf_sync.ui.calibration_widget import SimpleCalibrationWidget
from nanoleaf_sync.ui.layout_helpers import mark_compact, mark_muted, stretch_all_combo_popups
from nanoleaf_sync.ui.preset_ui import (
    COLOR_STYLE_LABELS,
    DISPLAY_PRESET_LABELS,
    EDGE_LOCALITY_LABELS,
    LIGHT_SPREAD_LABELS,
    MOTION_PRESET_LABELS,
    PERFORMANCE_PRIORITY_LABELS,
    PERFORMANCE_PROFILE_LABELS,
    SAMPLING_QUALITY_LABELS,
    label_for_value,
    labels,
)
from nanoleaf_sync.ui.settings_dialog_shared import (
    FPS_MAX,
    FPS_MIN,
    HDR_MAX_NITS_MAX,
    HDR_MAX_NITS_MIN,
    MAX_ZONE_COUNT,
    SDR_BOOST_NITS_MAX,
    SDR_BOOST_NITS_MIN,
    SETTINGS_SECTIONS,
    _FallbackLayout,
    _FallbackScrollArea,
    _FallbackWidget,
    _qt_widget,
)


class SettingsDialogWidgetBase:
    def __init__(
        self,
        parent,
        cfg: AppConfig,
        *,
        qt,
        calibration_sender=None,
        diagnostic_capture=None,
        runtime_status=None,
        initial_section=None,
        on_apply=None,
        dialog_geometry=None,
        forget_portal_token_fn=None,
    ):
        super().__init__(parent)
        self._qt = qt
        self._cfg_seed = cfg
        qt = self._qt
        QDialogButtonBox = qt["QDialogButtonBox"]
        QGridLayout = qt["QGridLayout"]
        QCheckBox = qt["QCheckBox"]
        QComboBox = qt["QComboBox"]
        QLineEdit = qt["QLineEdit"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]
        QTimer = qt["QTimer"]
        self.QTimer = QTimer
        QScrollArea = _qt_widget(qt, "QScrollArea", _FallbackScrollArea)
        QHBoxLayout = _qt_widget(qt, "QHBoxLayout", _FallbackLayout)
        QListWidget = qt["QListWidget"]
        QStackedWidget = qt["QStackedWidget"]
        QVBoxLayout = _qt_widget(qt, "QVBoxLayout", _FallbackLayout)
        QGroupBox = _qt_widget(qt, "QGroupBox", _FallbackWidget)
        _qt_widget(qt, "QWidget", _FallbackWidget)
        window_title = "nanoleaf-kde-sync Settings"
        self.setWindowTitle(window_title)
        resize = getattr(self, "resize", None)
        if callable(resize):
            resize(980, 760)
        set_minimum_width = getattr(self, "setMinimumWidth", None)
        if callable(set_minimum_width):
            set_minimum_width(980)
        if dialog_geometry is not None:
            restore = getattr(self, "restoreGeometry", None)
            if callable(restore):
                restore(dialog_geometry)
        self._open_display_configurator = False
        self._calibration_sender = calibration_sender
        self._diagnostic_capture = diagnostic_capture
        self._runtime_status = dict(runtime_status or {})
        self._probe_session_state: dict[str, object] = {}
        self._on_apply = on_apply
        self._forget_portal_token_fn = forget_portal_token_fn
        self._state = CalibrationState.from_config(self._cfg_seed, runtime_status)
        self._device_ids_manual = False
        self._syncing_device_model = False
        self._led_profile_sdr = copy.deepcopy(
            getattr(self._cfg_seed, "led_calibration_profile_sdr", LedCalibrationProfile())
        )
        self._led_profile_hdr = copy.deepcopy(
            getattr(self._cfg_seed, "led_calibration_profile_hdr", LedCalibrationProfile())
        )
        self._active_display_preset = (
            str(getattr(self._cfg_seed, "display_preset", "hdr") or "hdr").strip().lower()
        )
        self._backend_probe_running = False
        self._source_zones_locked_to_device_count = (
            not bool(self._state.source_zones_user_configured)
            and str(self._state.layout_preset) == "edge_strip"
        )
        self._test_step = 0
        self._latest_latency = None
        self._section_widgets: dict[str, object] = {}
        self._section_stack = None
        self._section_nav = None
        self._settings_applied_in_session = False
        self._preview_refresh_timer = QTimer(self)
        self._preview_refresh_timer.setSingleShot(True)
        self._preview_refresh_timer.timeout.connect(self._refresh_preview_label)
        self.screen_zone_matched_label = QLabel("")
        self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(int(round(self._cfg_seed.brightness * 100)))
        self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.smoothing_slider.setRange(0, 100)
        self.smoothing_slider.setValue(int(round(self._cfg_seed.smoothing * 100)))
        self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.smoothing_speed_slider.setRange(0, 400)
        self.smoothing_speed_slider.setValue(
            int(round(getattr(self._cfg_seed, "smoothing_speed", 0.75) * 100))
        )
        self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.fps_slider.setRange(FPS_MIN, FPS_MAX)
        self.fps_slider.setValue(int(self._cfg_seed.fps))
        self.display_preset_combo = QComboBox()
        self.display_preset_combo.addItems(labels(DISPLAY_PRESET_LABELS))
        self.display_preset_combo.setCurrentIndex(
            max(
                0,
                self.display_preset_combo.findText(
                    label_for_value(
                        DISPLAY_PRESET_LABELS,
                        str(getattr(self._cfg_seed, "display_preset", "hdr")),
                        default="HDR",
                    )
                ),
            )
        )
        self.compositor_hdr_mode_checkbox = QCheckBox("Compositor HDR mode (KDE Plasma SDR-on-HDR)")
        self.compositor_hdr_mode_checkbox.setChecked(
            bool(getattr(self._cfg_seed, "compositor_hdr_mode", False))
        )
        self.sdr_boost_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.sdr_boost_nits_slider.setRange(SDR_BOOST_NITS_MIN, SDR_BOOST_NITS_MAX)
        self.sdr_boost_nits_slider.setValue(int(getattr(self._cfg_seed, "sdr_boost_nits", 80.0)))
        self.sdr_boost_nits_value = QLabel("")
        self.sdr_white_reference_preset_combo = QComboBox()
        self.sdr_white_reference_preset_combo.addItems(
            ["80 nits", "120 nits", "160 nits", "203 nits", "Custom"]
        )
        self.detect_sdr_white_button = QPushButton("Detect KDE SDR white reference")
        self.use_detected_sdr_white_button = QPushButton("Use detected value")
        self.detected_sdr_white_label = QLabel("Detected value: unavailable")
        preset_value = (
            str(getattr(self._cfg_seed, "sdr_white_reference_preset", "80")).strip().lower()
        )
        self.sdr_white_reference_preset_combo.setCurrentIndex(
            {"80": 0, "120": 1, "160": 2, "203": 3, "custom": 4}.get(preset_value, 4)
        )
        self.motion_preset_combo = QComboBox()
        self.motion_preset_combo.addItems(labels(MOTION_PRESET_LABELS))
        self.motion_preset_combo.setCurrentIndex(
            max(
                0,
                self.motion_preset_combo.findText(
                    label_for_value(
                        MOTION_PRESET_LABELS,
                        str(getattr(self._cfg_seed, "motion_preset", "responsive")),
                        default="Responsive",
                    )
                ),
            )
        )
        self.color_style_combo = QComboBox()
        self.color_style_combo.addItems(labels(COLOR_STYLE_LABELS))
        self.color_style_combo.setCurrentIndex(
            max(
                0,
                self.color_style_combo.findText(
                    label_for_value(
                        COLOR_STYLE_LABELS,
                        str(getattr(self._cfg_seed, "color_style", "ambient")),
                        default="Ambient (recommended)",
                    )
                ),
            )
        )
        self.edge_locality_combo = QComboBox()
        self.edge_locality_combo.addItems(labels(EDGE_LOCALITY_LABELS))
        self.edge_locality_combo.setCurrentIndex(
            max(
                0,
                self.edge_locality_combo.findText(
                    label_for_value(
                        EDGE_LOCALITY_LABELS,
                        str(getattr(self._cfg_seed, "edge_locality", "balanced")),
                        default="Tight",
                    )
                ),
            )
        )
        self.light_spread_combo = QComboBox()
        self.light_spread_combo.addItems(labels(LIGHT_SPREAD_LABELS))
        self.light_spread_combo.setCurrentIndex(
            max(
                0,
                self.light_spread_combo.findText(
                    label_for_value(
                        LIGHT_SPREAD_LABELS,
                        str(getattr(self._cfg_seed, "light_spread", "balanced")),
                        default="Balanced",
                    )
                ),
            )
        )
        self.start_on_launch_checkbox = QCheckBox(
            "Start mirroring automatically when tray app opens"
        )
        self.start_on_launch_checkbox.setChecked(
            bool(getattr(self._cfg_seed, "start_on_launch", False))
        )
        self.four_d_sync_checkbox = QCheckBox("4D sync (120fps edge mirroring + prediction)")
        self.four_d_sync_checkbox.setChecked(
            str(getattr(self._cfg_seed, "sync_mode", "standard")).strip().lower() == "4d"
        )
        self.display_gamut_combo = QComboBox()
        self.display_gamut_combo.addItems(["Auto", "sRGB", "DCI-P3", "BT.2020", "Custom"])
        gamut_text = str(getattr(self._cfg_seed, "display_gamut", "auto")).strip().lower()
        gamut_map = {
            "auto": "Auto",
            "srgb": "sRGB",
            "dci-p3": "DCI-P3",
            "bt.2020": "BT.2020",
            "bt2020": "BT.2020",
            "custom": "Custom",
        }
        self.display_gamut_combo.setCurrentIndex(
            max(0, self.display_gamut_combo.findText(gamut_map.get(gamut_text, "Auto")))
        )

        self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.zone_count_slider.setRange(1, MAX_ZONE_COUNT)
        self.zone_count_slider.setValue(self._state.zone_count)
        self.simple_calibration_widget = SimpleCalibrationWidget(qt=qt, title="Corner calibration")
        self.reverse_checkbox = self.simple_calibration_widget.reverse_orientation_checkbox
        self.reverse_checkbox.setChecked(self._state.reverse_zones)
        self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.device_zone_count_slider.setRange(1, self._device_zone_count_max())
        self.device_zone_count_slider.setValue(self._state.device_zone_count)
        self.device_zone_count_status_label = QLabel("")
        self.strip_count_warning_label = QLabel("")
        self.use_detected_count_button = QPushButton("Use reported count")
        self.keep_configured_count_button = QPushButton("Keep manual count")
        self.reset_recalibrate_button = QPushButton("Reset anchors and recalibrate")
        self.assign_top_left_button = self.simple_calibration_widget.assign_top_left_button
        self.assign_top_right_button = self.simple_calibration_widget.assign_top_right_button
        self.assign_bottom_right_button = self.simple_calibration_widget.assign_bottom_right_button
        self.assign_bottom_left_button = self.simple_calibration_widget.assign_bottom_left_button
        self.reset_anchor_button = self.simple_calibration_widget.reset_anchors_button
        self.current_zone_label = self.simple_calibration_widget.current_zone_label
        self.test_step_index_label = self.simple_calibration_widget.step_index_label

        self.test_step_button = self.simple_calibration_widget.next_zone_button
        self.test_prev_button = self.simple_calibration_widget.prev_zone_button
        self._live_preview_timer = QTimer(self)
        live_single_shot = getattr(self._live_preview_timer, "setSingleShot", None)
        if callable(live_single_shot):
            live_single_shot(True)
        self._live_preview_timer.timeout.connect(self._flush_live_preview)

        self.output_channel_order_combo = QComboBox()
        self.output_channel_order_combo.addItems(["grb", "rgb", "rbg", "gbr", "brg", "bgr"])
        self.output_channel_order_combo.setCurrentIndex(
            max(
                0,
                self.output_channel_order_combo.findText(
                    str(getattr(self._cfg_seed, "output_channel_order", "grb"))
                ),
            )
        )
        self.device_model_combo = QComboBox()
        self.device_model_combo.addItems(
            ["NL82K2 Lightstrip (PID 0x8202)", "NL82K1 Dock (PID 0x8201)", "Custom VID/PID"]
        )
        self.device_vid_combo = QComboBox()
        self.device_vid_combo.addItems(["0x37FA"])
        self.device_pid_combo = QComboBox()
        self.device_pid_combo.addItems(["0x8202", "0x8201"])
        vid_hex = f"0x{int(getattr(self._cfg_seed, 'device_vid', 0x37FA)):04X}"
        pid_hex = f"0x{int(getattr(self._cfg_seed, 'device_pid', 0x8202)):04X}"
        if self.device_vid_combo.findText(vid_hex) < 0:
            self.device_vid_combo.addItems([vid_hex])
        if self.device_pid_combo.findText(pid_hex) < 0:
            self.device_pid_combo.addItems([pid_hex])
        self.device_vid_combo.setCurrentIndex(max(0, self.device_vid_combo.findText(vid_hex)))
        self.device_pid_combo.setCurrentIndex(max(0, self.device_pid_combo.findText(pid_hex)))
        self.allow_custom_device_ids_checkbox = QCheckBox("Allow custom USB device IDs (advanced)")
        self.allow_custom_device_ids_checkbox.setChecked(
            bool(getattr(self._cfg_seed, "allow_custom_device_ids", False))
        )
        if pid_hex == "0x8201":
            self.device_model_combo.setCurrentIndex(1)
        elif pid_hex == "0x8202":
            self.device_model_combo.setCurrentIndex(0)
        else:
            self.device_model_combo.setCurrentIndex(2)
        self.capture_backend_combo = QComboBox()
        self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"])
        self.capture_backend_combo.setCurrentIndex(
            max(
                0,
                self.capture_backend_combo.findText(
                    str(getattr(self._cfg_seed, "prefer_backend", "kwin-dbus"))
                ),
            )
        )
        self.capture_monitor_edit = QLineEdit()
        self.capture_monitor_edit.setPlaceholderText("empty = Plasma primary output")
        self.capture_monitor_edit.setText(str(getattr(self._cfg_seed, "capture_monitor", "") or ""))
        self.auto_probe_policy_combo = QComboBox()
        self.auto_probe_policy_combo.addItems(["on-change", "first-run", "each-boot"])
        self.auto_probe_policy_combo.setCurrentIndex(
            max(
                0,
                self.auto_probe_policy_combo.findText(
                    str(getattr(self._cfg_seed, "auto_probe_policy", "on-change"))
                ),
            )
        )

        self.auto_latency_policy_combo = QComboBox()
        self.auto_latency_policy_combo.addItems(["manual", "on-open", "on-open-once-per-backend"])
        self.auto_latency_policy_combo.setCurrentIndex(
            max(
                0,
                self.auto_latency_policy_combo.findText(
                    str(getattr(self._cfg_seed, "auto_latency_policy", "manual"))
                ),
            )
        )
        self.run_latency_button = QPushButton("Measure active backend latency")
        self.retest_backends_button = QPushButton("Re-test backends (fresh probe)")
        self.test_xdg_portal_button = QPushButton("Test xdg-portal")
        self.benchmark_xdg_portal_button = QPushButton("Benchmark xdg-portal")
        self.reset_portal_screen_button = QPushButton("Reset portal screen selection")
        self.latency_label = QLabel(latency_result_summary(None))
        self.xdg_hint_label = QLabel("")

        self.hdr_transfer_combo = QComboBox()
        self.hdr_transfer_combo.addItems(["srgb", "pq"])
        self.hdr_transfer_combo.setCurrentIndex(
            max(
                0,
                self.hdr_transfer_combo.findText(
                    str(getattr(self._cfg_seed, "hdr_transfer", AppConfig.hdr_transfer))
                ),
            )
        )
        self.hdr_primaries_combo = QComboBox()
        self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
        self.hdr_primaries_combo.setCurrentIndex(
            max(
                0,
                self.hdr_primaries_combo.findText(
                    str(getattr(self._cfg_seed, "hdr_primaries", AppConfig.hdr_primaries))
                ),
            )
        )
        self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.hdr_max_nits_slider.setRange(HDR_MAX_NITS_MIN, HDR_MAX_NITS_MAX)
        self.hdr_max_nits_slider.setValue(int(getattr(self._cfg_seed, "hdr_max_nits", 1000.0)))
        self.sampling_quality_combo = QComboBox()
        self.sampling_quality_combo.addItems(labels(SAMPLING_QUALITY_LABELS))
        self.sampling_quality_combo.setCurrentIndex(
            max(
                0,
                self.sampling_quality_combo.findText(
                    label_for_value(
                        SAMPLING_QUALITY_LABELS,
                        str(getattr(self._cfg_seed, "sampling_quality", "balanced")),
                        default="Balanced",
                    )
                ),
            )
        )
        self.performance_profile_combo = QComboBox()
        self.performance_profile_combo.addItems(labels(PERFORMANCE_PROFILE_LABELS))
        self.performance_profile_combo.setCurrentIndex(
            max(
                0,
                self.performance_profile_combo.findText(
                    label_for_value(
                        PERFORMANCE_PROFILE_LABELS,
                        str(getattr(self._cfg_seed, "performance_profile", "balanced")),
                        default="Balanced",
                    )
                ),
            )
        )
        self.performance_priority_combo = QComboBox()
        self.performance_priority_combo.addItems(labels(PERFORMANCE_PRIORITY_LABELS))
        self.performance_priority_combo.setCurrentIndex(
            max(
                0,
                self.performance_priority_combo.findText(
                    label_for_value(
                        PERFORMANCE_PRIORITY_LABELS,
                        str(getattr(self._cfg_seed, "performance_priority", "normal")),
                        default="Normal",
                    )
                ),
            )
        )
        self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.led_gamma_slider.setRange(100, 400)
        self.led_gamma_slider.setValue(int(round(getattr(self._cfg_seed, "led_gamma", 1.0) * 100)))
        self.red_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.red_gain_slider.setRange(50, 150)
        self.red_gain_slider.setValue(int(round(getattr(self._cfg_seed, "red_gain", 1.0) * 100)))
        self.green_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.green_gain_slider.setRange(50, 150)
        self.green_gain_slider.setValue(
            int(round(getattr(self._cfg_seed, "green_gain", 1.0) * 100))
        )
        self.blue_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.blue_gain_slider.setRange(50, 150)
        self.blue_gain_slider.setValue(int(round(getattr(self._cfg_seed, "blue_gain", 1.0) * 100)))
        self.white_balance_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.white_balance_slider.setRange(-100, 100)
        self.white_balance_slider.setValue(
            int(round(getattr(self._cfg_seed, "white_balance_temperature", 0.0) * 100))
        )
        self.chroma_compression_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.chroma_compression_slider.setRange(0, 60)
        self.chroma_compression_slider.setValue(
            int(round(getattr(self._cfg_seed, "chroma_compression", 0.0) * 100))
        )
        self.neutral_luminance_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.neutral_luminance_gain_slider.setRange(70, 150)
        self.neutral_luminance_gain_slider.setValue(
            int(round(getattr(self._cfg_seed, "neutral_luminance_gain", 1.0) * 100))
        )
        self.black_luminance_cutoff_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.black_luminance_cutoff_slider.setRange(0, 300)
        self.black_luminance_cutoff_slider.setValue(
            int(round(getattr(self._cfg_seed, "black_luminance_cutoff", 0.0032) * 10000))
        )
        self.black_luminance_knee_slider = QSlider(qt["Qt"].Orientation.Horizontal)
        self.black_luminance_knee_slider.setRange(5, 300)
        self.black_luminance_knee_slider.setValue(
            int(round(getattr(self._cfg_seed, "black_luminance_knee", 0.0024) * 10000))
        )
        self._load_led_profile_sliders(self._active_display_preset)
        self.reset_led_calibration_button = QPushButton("Reset calibration")
        self.reference_test_colours_button = QPushButton("Reference test colours")
        self.guided_led_calibration_button = QPushButton("Calibrate LED colour")
        self.save_led_calibration_profile_button = QPushButton("Save active calibration profile")
        self.export_led_calibration_profile_button = QPushButton("Export measured LED profile")
        self.import_led_calibration_profile_button = QPushButton("Import measured LED profile")
        self._apply_tooltips()

        self.backend_info_label = QLabel("")
        self.diagnostics_mapping_label = QLabel("")
        self.hdr_colour_path_label = QLabel("")
        self.edge_locality_diagnostic_button = QPushButton("Run edge locality test")
        self.edge_locality_diagnostic_label = QLabel("")
        self.color_accuracy_diagnostic_button = QPushButton("Run colour accuracy diagnostic")
        self.color_accuracy_diagnostic_label = QLabel("")
        self.run_self_check_button = QPushButton("Run self-check")
        self.capture_one_diagnostic_frame_button = QPushButton("Capture one diagnostic frame")
        self.export_live_sampling_overlay_button = QPushButton("Export live sampling overlay")
        self.export_synthetic_sampling_overlay_button = QPushButton(
            "Export synthetic sampling test overlay"
        )
        self.export_zone_report_button = QPushButton("Export per-zone colour report")
        self.export_latency_report_button = QPushButton("Export live latency breakdown")
        self.self_check_label = QLabel("")
        self.sampling_export_label = QLabel("")
        self.zone_report_label = QLabel("")
        self.latency_report_label = QLabel("")
        self.recovery_tools_hint_label = QLabel(
            "Use tray Advanced / Troubleshooting for Run Doctor, Run Smoke Test, "
            "launch diagnostics, and probe cache reset."
        )
        self.preview_label = self.simple_calibration_widget.preview_text_label
        self.preview_visual_label = self.simple_calibration_widget.preview_visual_label
        self.test_label = QLabel("")
        self.brightness_value = QLabel("")
        self.smoothing_value = QLabel("")
        self.fps_value = QLabel("")
        self.zone_count_value = QLabel("")
        self.device_zone_count_value = QLabel("")
        self.hdr_max_nits_value = QLabel("")
        self.sdr_boost_nits_value = QLabel("")
        self.sampling_quality_value = QLabel("")
        self.smoothing_speed_value = QLabel("")
        self.led_gamma_value = QLabel("")
        self.red_gain_value = QLabel("")
        self.green_gain_value = QLabel("")
        self.blue_gain_value = QLabel("")
        self.white_balance_value = QLabel("")
        self.chroma_compression_value = QLabel("")
        self.neutral_luminance_gain_value = QLabel("")
        self.black_luminance_cutoff_value = QLabel("")
        self.black_luminance_knee_value = QLabel("")
        for label in (
            self.brightness_value,
            self.smoothing_value,
            self.fps_value,
            self.zone_count_value,
            self.device_zone_count_value,
            self.hdr_max_nits_value,
            self.sdr_boost_nits_value,
            self.sampling_quality_value,
            self.smoothing_speed_value,
            self.led_gamma_value,
            self.red_gain_value,
            self.green_gain_value,
            self.blue_gain_value,
            self.white_balance_value,
            self.chroma_compression_value,
            self.neutral_luminance_gain_value,
            self.black_luminance_cutoff_value,
            self.black_luminance_knee_value,
        ):
            self._configure_value_label(label)
        self._bind_live_numeric_updates()

        for signal in (
            self.performance_profile_combo.currentIndexChanged,
            self.reverse_checkbox.stateChanged,
            self.capture_backend_combo.currentIndexChanged,
            self.auto_probe_policy_combo.currentIndexChanged,
        ):
            signal.connect(self._refresh_preview_label)
        self.display_preset_combo.currentIndexChanged.connect(self._on_display_preset_changed)
        for slider in (
            self.led_gamma_slider,
            self.red_gain_slider,
            self.green_gain_slider,
            self.blue_gain_slider,
            self.white_balance_slider,
            self.chroma_compression_slider,
            self.neutral_luminance_gain_slider,
            self.black_luminance_cutoff_slider,
            self.black_luminance_knee_slider,
        ):
            slider.valueChanged.connect(self._schedule_refresh_preview_label)
        self.zone_count_slider.valueChanged.connect(self._on_zone_count_slider_changed)
        self.performance_profile_combo.currentIndexChanged.connect(
            self._on_performance_profile_changed
        )
        self.device_zone_count_slider.valueChanged.connect(
            self._on_device_zone_count_slider_changed
        )
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
            on_flash_assigned_corners=self._send_test_pattern,
            on_walk_strip_once=self._walk_strip_once,
        )
        self.run_latency_button.clicked.connect(self._run_latency_probe_manual)
        self.retest_backends_button.clicked.connect(self._run_fresh_backend_probe)
        self._update_backend_probe_button_state()
        self.test_xdg_portal_button.clicked.connect(self._run_xdg_portal_test)
        self.benchmark_xdg_portal_button.clicked.connect(self._run_xdg_portal_benchmark)
        self.reset_portal_screen_button.clicked.connect(self._reset_portal_screen_selection)
        self.edge_locality_diagnostic_button.clicked.connect(self._run_edge_locality_diagnostic)
        self.color_accuracy_diagnostic_button.clicked.connect(self._run_color_accuracy_diagnostic)
        self.run_self_check_button.clicked.connect(self._run_self_check)
        self.capture_one_diagnostic_frame_button.clicked.connect(self._capture_one_diagnostic_frame)
        self.export_live_sampling_overlay_button.clicked.connect(self._export_live_sampling_overlay)
        self.export_synthetic_sampling_overlay_button.clicked.connect(
            self._export_synthetic_sampling_overlay
        )
        self.export_zone_report_button.clicked.connect(self._export_zone_report)
        self.export_latency_report_button.clicked.connect(self._export_latency_report)
        self.use_detected_count_button.clicked.connect(self._use_detected_strip_count)
        self.keep_configured_count_button.clicked.connect(self._keep_configured_strip_count)
        self.reset_recalibrate_button.clicked.connect(self._reset_anchors)
        self.device_model_combo.currentIndexChanged.connect(self._sync_device_model_selection)
        self.device_vid_combo.currentIndexChanged.connect(self._on_device_usb_id_edited)
        self.device_pid_combo.currentIndexChanged.connect(self._on_device_usb_id_edited)
        self.sdr_boost_nits_slider.valueChanged.connect(self._on_sdr_white_slider_changed)
        self.sdr_white_reference_preset_combo.currentIndexChanged.connect(
            self._on_sdr_white_preset_changed
        )
        self.detect_sdr_white_button.clicked.connect(self._detect_kde_sdr_white_reference)
        self.use_detected_sdr_white_button.clicked.connect(self._use_detected_sdr_white_reference)
        self.reset_led_calibration_button.clicked.connect(self._reset_led_calibration)
        self.reference_test_colours_button.clicked.connect(self._send_reference_test_colours)
        self.guided_led_calibration_button.clicked.connect(self._open_guided_led_calibration)
        self.save_led_calibration_profile_button.clicked.connect(
            self._save_active_led_calibration_profile
        )
        self.export_led_calibration_profile_button.clicked.connect(
            self._export_led_calibration_profile
        )
        self.import_led_calibration_profile_button.clicked.connect(
            self._import_led_calibration_profile
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        buttons.accepted.connect(self._apply_settings)
        buttons.rejected.connect(self.reject)

        set_quit_attr = getattr(self, "setAttribute", None)
        if callable(set_quit_attr):
            set_quit_attr(qt["Qt"].WidgetAttribute.WA_QuitOnClose, False)

        everyday_section = self._build_everyday_section(QGroupBox, QGridLayout, QLabel)
        strip_setup_section = self._build_strip_setup_section(
            QGroupBox, QGridLayout, QLabel, QScrollArea
        )
        fine_tuning_section = self._build_fine_tuning_section(QGroupBox, QGridLayout, QLabel)
        colour_section = self._build_colour_section(QGroupBox, QGridLayout, QLabel)
        advanced_section = self._build_advanced_section(QGroupBox, QGridLayout, QLabel)

        self._section_widgets = {
            "Everyday": everyday_section,
            "Strip setup": strip_setup_section,
            "Fine-tuning": fine_tuning_section,
            "Colour": colour_section,
            "Advanced": advanced_section,
        }

        stack = QStackedWidget()
        self._section_stack = stack
        for section_name in SETTINGS_SECTIONS:
            stack.addWidget(self._section_widgets[section_name])

        section_nav = QListWidget()
        self._section_nav = section_nav
        for section_name in SETTINGS_SECTIONS:
            section_nav.addItem(section_name)
        section_nav.setFixedWidth(160)
        section_nav.currentRowChanged.connect(stack.setCurrentIndex)

        body_layout = QHBoxLayout()
        body_layout.addWidget(section_nav)
        body_layout.addWidget(stack, 1)

        root = QVBoxLayout()
        root.addLayout(body_layout)
        root.addWidget(buttons)
        self.setLayout(root)

        self._sync_device_model_selection()
        self._refresh_numeric_labels()
        self._refresh_preview_label()
        self._update_latency_label_for_latest_probe_result()
        self._maybe_auto_run_latency_check()
        if initial_section:
            self.focus_section(initial_section)
        else:
            section_nav.setCurrentRow(0)

        self._compact_action_buttons = [
            self.detect_sdr_white_button,
            self.use_detected_sdr_white_button,
            self.use_detected_count_button,
            self.keep_configured_count_button,
            self.reset_recalibrate_button,
            self.run_latency_button,
            self.retest_backends_button,
            self.test_xdg_portal_button,
            self.benchmark_xdg_portal_button,
            self.reset_led_calibration_button,
            self.reference_test_colours_button,
            self.guided_led_calibration_button,
            self.save_led_calibration_profile_button,
            self.export_led_calibration_profile_button,
            self.import_led_calibration_profile_button,
            self.edge_locality_diagnostic_button,
            self.color_accuracy_diagnostic_button,
            self.run_self_check_button,
            self.capture_one_diagnostic_frame_button,
            self.export_live_sampling_overlay_button,
            self.export_synthetic_sampling_overlay_button,
            self.export_zone_report_button,
            self.export_latency_report_button,
        ]
        for button in self._compact_action_buttons:
            mark_compact(button)
        for label in (
            self.device_zone_count_status_label,
            self.strip_count_warning_label,
            self.screen_zone_matched_label,
            self.test_label,
            self.simple_calibration_widget.preview_text_label,
            self.simple_calibration_widget.current_zone_label,
            self.simple_calibration_widget.assigned_corners_label,
            self.simple_calibration_widget.corner_checklist_label,
            self.simple_calibration_widget.direction_label,
            self.simple_calibration_widget.validation_label,
            self.simple_calibration_widget.preview_visual_label,
            self.latency_label,
            self.self_check_label,
            self.sampling_export_label,
            self.zone_report_label,
            self.latency_report_label,
            self.edge_locality_diagnostic_label,
            self.color_accuracy_diagnostic_label,
            self.backend_info_label,
            self.diagnostics_mapping_label,
            self.hdr_colour_path_label,
            self.xdg_hint_label,
            self.recovery_tools_hint_label,
        ):
            self._configure_wrapping_label(label)
            mark_muted(label)
        stretch_all_combo_popups(self)
        self._baseline_config = self.updated_config()

    def _apply_tooltips(self) -> None:
        self.brightness_slider.setToolTip(
            "Overall output intensity. Lower values reduce LED brightness."
        )
        self.smoothing_slider.setToolTip("Blends frame-to-frame colors to reduce flicker.")
        self.smoothing_speed_slider.setToolTip(
            "Motion response gain for smoothing. Lower values react slower "
            "(more smoothing); 0 keeps the strongest smoothing."
        )
        self.fps_slider.setToolTip(
            "This is the target update rate. Actual output FPS may be lower if "
            "capture, processing, or HID output cannot keep up."
        )
        self.sampling_quality_combo.setToolTip(
            "Low = better performance, Balanced = default, High = best visual fidelity."
        )
        self.performance_profile_combo.setToolTip(
            "Performance lowers capture cost, Balanced is the recommended default, "
            "Quality prioritizes colour and sampling fidelity."
        )
        self.performance_priority_combo.setToolTip(
            "High priority may improve scheduling consistency. It may fail without "
            "permission. Very high is experimental."
        )
        self.led_gamma_slider.setToolTip(
            "Gamma correction for LED response. 1.00 keeps output linear."
        )
        self.zone_count_slider.setToolTip(
            "Number of screen sampling zones sampled from the display."
        )
        self.reverse_checkbox.setToolTip("Flip strip direction if the mapping appears mirrored.")
        self.display_preset_combo.setToolTip(
            "Select SDR, HDR, or Auto display behavior. "
            "Changing this while mirroring may need a restart for full effect."
        )
        self.motion_preset_combo.setToolTip(
            "Calm: smoother fades for video and desktop. "
            "Responsive: adaptive default for games and general use. "
            "Dynamic: fastest response with basic flicker control."
        )
        self.color_style_combo.setToolTip(
            "Reference: Most accurate. Preserves greys as neutral light, "
            "avoids saturation boost, turns off only for black/near-black.\n"
            "Ambient: Recommended glow. Similar to Reference, with slightly "
            "stronger neutral brightness and smoother ambience.\n"
            "Vivid: Richer colour response.\n"
            "Punchy: Strong stylised colour effect."
        )
        self.edge_locality_combo.setToolTip(
            "Tight: most accurate/least bleed. Balanced: softer ambient look. "
            "Wide: cinematic blend."
        )
        self.light_spread_combo.setToolTip(
            "Neighbour blending only. Precise = least spread, Balanced = default, Soft = cinematic."
        )
        self.hdr_max_nits_slider.setToolTip(
            "Reference display peak brightness for HDR tone mapping."
        )
        self.capture_backend_combo.setToolTip("Select auto or force a specific capture backend.")
        self.device_model_combo.setToolTip("Select your Nanoleaf USB hardware model.")
        self.device_vid_combo.setToolTip("USB vendor ID used to locate your hardware.")
        self.device_pid_combo.setToolTip("USB product ID used to locate your hardware.")
        self.auto_probe_policy_combo.setToolTip("Choose when auto-backend probing should run.")
        self.auto_latency_policy_combo.setToolTip(
            "Automatically run latency checks on selected lifecycle events."
        )
        self.device_zone_count_slider.setToolTip(
            "Configured strip zone count used for device mapping."
        )
        self.output_channel_order_combo.setToolTip(
            "Set RGB byte order expected by your strip controller."
        )
        self.start_on_launch_checkbox.setToolTip(
            "Start syncing automatically right after tray launch."
        )
        self.four_d_sync_checkbox.setToolTip(
            "Low-latency edge mirroring for high FPS: faster HID send, "
            "balanced zone sampling, tight edge locality, and predictive colour sync."
        )
        self.compositor_hdr_mode_checkbox.setToolTip(
            "Enable compensation when KDE Plasma is running SDR content on HDR. "
            "Restart mirroring after changing for full effect."
        )
        self.sdr_boost_nits_slider.setToolTip(
            "Plasma SDR white reference in nits when compositor HDR mode is enabled."
        )
        self.sdr_white_reference_preset_combo.setToolTip(
            "Preset SDR white reference levels (80/120/160/203 nits or custom)."
        )
        self.chroma_compression_slider.setToolTip("Chroma compression: reduces LED oversaturation.")
        self.neutral_luminance_gain_slider.setToolTip(
            "Neutral luminance: controls how bright grey/white screen areas appear on the LEDs."
        )
        self.black_luminance_cutoff_slider.setToolTip(
            "Black cutoff: controls when near-black screen areas turn the LEDs off."
        )
        self.white_balance_slider.setToolTip("White balance: adjusts LED tint warmer/cooler.")
