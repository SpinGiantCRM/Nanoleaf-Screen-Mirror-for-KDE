from __future__ import annotations

from dataclasses import replace
import logging
from typing import Callable

import numpy as np

_log = logging.getLogger(__name__)

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, LedCalibrationProfile
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
    LIGHT_SPREAD_LABELS,
    MOTION_PRESET_LABELS,
    SAMPLING_QUALITY_LABELS,
    PERFORMANCE_PRIORITY_LABELS,
    label_for_value,
    labels,
    value_for_label,
)
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.runtime.edge_locality_diagnostics import run_edge_locality_test
from nanoleaf_sync.runtime.color_accuracy_diagnostics import run_color_accuracy_diagnostic
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
    color_pipeline_diagnostics,
)
from nanoleaf_sync.runtime.readiness_check import run_readiness_check
from nanoleaf_sync.runtime.compositor import effective_sdr_boost
from nanoleaf_sync.runtime.diagnostics_exports import (
    diagnostics_text_lines,
    export_latency_report,
    export_sampling_overlay,
    format_backend_attempt_row,
    export_zone_report,
)
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.ui.led_color_calibration_dialog import LedColorCalibrationDialog
from nanoleaf_sync.capture.factory import (
    run_explicit_xdg_portal_probe,
    run_fresh_backend_probe,
    run_manual_portal_benchmark,
)

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

SETTINGS_VIEW_STANDARD = "standard"
SETTINGS_VIEW_ADVANCED = "advanced"

class _FallbackLayout:
    def addWidget(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QVBoxLayout unavailable; settings UI degraded.")
        return None

    def addLayout(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QVBoxLayout unavailable; settings UI degraded.")
        return None

    def addStretch(self, *_args, **_kwargs) -> None:
        return None


class _FallbackWidget:
    def __init__(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QWidget/QGroupBox unavailable; settings UI degraded.")
        return None

    def setLayout(self, *_args, **_kwargs) -> None:
        return None


class _FallbackScrollArea:
    def setWidgetResizable(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QScrollArea unavailable; settings UI degraded.")
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
        diagnostic_capture: Callable[[], dict[str, object]] | None = None,
        runtime_status: dict | None = None,
        initial_section: str | None = None,
        on_apply: Callable[[AppConfig], None] | None = None,
        view_mode: str = SETTINGS_VIEW_STANDARD,
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
                window_title = "nanoleaf-kde-sync Settings" if view_mode != SETTINGS_VIEW_ADVANCED else "nanoleaf-kde-sync Advanced / Troubleshooting"
                self.setWindowTitle(window_title)
                resize = getattr(self, "resize", None)
                if callable(resize):
                    resize(860, 760)
                self._open_display_configurator = False
                self._calibration_sender = calibration_sender
                self._diagnostic_capture = diagnostic_capture
                self._runtime_status = runtime_status or {}
                self._on_apply = on_apply
                self._state = CalibrationState.from_config(cfg, runtime_status)
                self._source_zones_locked_to_device_count = (
                    not bool(self._state.source_zones_user_configured)
                    and str(self._state.layout_preset) == "edge-weighted"
                )
                self._test_step = 0
                self._latest_latency = None
                self._section_widgets: dict[str, object] = {}
                self._settings_scroll = None
                self._view_mode = str(view_mode or SETTINGS_VIEW_STANDARD).strip().lower()

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.brightness_slider.setRange(0, 100); self.brightness_slider.setValue(int(round(cfg.brightness * 100)))
                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_slider.setRange(0, 100); self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))
                self.smoothing_speed_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.smoothing_speed_slider.setRange(0, 400); self.smoothing_speed_slider.setValue(int(round(getattr(cfg, "smoothing_speed", 0.75) * 100)))
                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.fps_slider.setRange(FPS_MIN, FPS_MAX); self.fps_slider.setValue(int(cfg.fps))
                self.display_preset_combo = QComboBox(); self.display_preset_combo.addItems(labels(DISPLAY_PRESET_LABELS)); self.display_preset_combo.setCurrentIndex(max(0, self.display_preset_combo.findText(label_for_value(DISPLAY_PRESET_LABELS, str(getattr(cfg, "display_preset", "hdr")), default="HDR"))))
                self.compositor_hdr_mode_checkbox = QCheckBox("Compositor HDR mode (KDE Plasma SDR-on-HDR)")
                self.compositor_hdr_mode_checkbox.setChecked(bool(getattr(cfg, "compositor_hdr_mode", False)))
                self.sdr_boost_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.sdr_boost_nits_slider.setRange(SDR_BOOST_NITS_MIN, SDR_BOOST_NITS_MAX); self.sdr_boost_nits_slider.setValue(int(getattr(cfg, "sdr_boost_nits", 80.0)))
                self.sdr_boost_nits_value = QLabel("")
                self.sdr_white_reference_preset_combo = QComboBox(); self.sdr_white_reference_preset_combo.addItems(["80 nits", "120 nits", "160 nits", "203 nits", "Custom"])
                self.detect_sdr_white_button = QPushButton("Detect KDE SDR white reference")
                self.use_detected_sdr_white_button = QPushButton("Use detected value")
                self.detected_sdr_white_label = QLabel("Detected value: unavailable")
                preset_value = str(getattr(cfg, "sdr_white_reference_preset", "80")).strip().lower()
                self.sdr_white_reference_preset_combo.setCurrentIndex({"80": 0, "120": 1, "160": 2, "203": 3, "custom": 4}.get(preset_value, 4))
                self.motion_preset_combo = QComboBox(); self.motion_preset_combo.addItems(labels(MOTION_PRESET_LABELS)); self.motion_preset_combo.setCurrentIndex(max(0, self.motion_preset_combo.findText(label_for_value(MOTION_PRESET_LABELS, str(getattr(cfg, "motion_preset", "responsive")), default="Responsive"))))
                self.color_style_combo = QComboBox(); self.color_style_combo.addItems(labels(COLOR_STYLE_LABELS)); self.color_style_combo.setCurrentIndex(max(0, self.color_style_combo.findText(label_for_value(COLOR_STYLE_LABELS, str(getattr(cfg, "color_style", "ambient")), default="Ambient (recommended)"))))
                self.edge_locality_combo = QComboBox(); self.edge_locality_combo.addItems(labels(EDGE_LOCALITY_LABELS)); self.edge_locality_combo.setCurrentIndex(max(0, self.edge_locality_combo.findText(label_for_value(EDGE_LOCALITY_LABELS, str(getattr(cfg, "edge_locality", "tight")), default="Tight"))))
                self.light_spread_combo = QComboBox(); self.light_spread_combo.addItems(labels(LIGHT_SPREAD_LABELS)); self.light_spread_combo.setCurrentIndex(max(0, self.light_spread_combo.findText(label_for_value(LIGHT_SPREAD_LABELS, str(getattr(cfg, "light_spread", "balanced")), default="Balanced"))))
                self.start_on_launch_checkbox = QCheckBox("Start mirroring automatically when tray app opens"); self.start_on_launch_checkbox.setChecked(bool(getattr(cfg, "start_on_launch", False)))
                self.display_gamut_combo = QComboBox(); self.display_gamut_combo.addItems(["Auto", "sRGB", "DCI-P3", "BT.2020", "Custom"])
                gamut_text = str(getattr(cfg, "display_gamut", "auto")).strip().lower()
                gamut_map = {"auto": "Auto", "srgb": "sRGB", "dci-p3": "DCI-P3", "bt.2020": "BT.2020", "bt2020": "BT.2020", "custom": "Custom"}
                self.display_gamut_combo.setCurrentIndex(max(0, self.display_gamut_combo.findText(gamut_map.get(gamut_text, "Auto"))))

                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.zone_count_slider.setRange(1, MAX_ZONE_COUNT); self.zone_count_slider.setValue(self._state.zone_count)
                self.simple_calibration_widget = SimpleCalibrationWidget(qt=qt, title="Corner calibration")
                self.reverse_checkbox = self.simple_calibration_widget.reverse_orientation_checkbox; self.reverse_checkbox.setChecked(self._state.reverse_zones)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.device_zone_count_slider.setRange(1, self._device_zone_count_max()); self.device_zone_count_slider.setValue(self._state.device_zone_count)
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
                self.capture_backend_combo = QComboBox(); self.capture_backend_combo.addItems(["auto", "kwin-dbus", "kmsgrab", "xdg-portal"]); self.capture_backend_combo.setCurrentIndex(max(0, self.capture_backend_combo.findText(str(getattr(cfg, "prefer_backend", "kwin-dbus")))))
                self.auto_probe_policy_combo = QComboBox(); self.auto_probe_policy_combo.addItems(["on-change", "first-run", "each-boot"]); self.auto_probe_policy_combo.setCurrentIndex(max(0, self.auto_probe_policy_combo.findText(str(getattr(cfg, "auto_probe_policy", "on-change")))))

                self.auto_latency_policy_combo = QComboBox(); self.auto_latency_policy_combo.addItems(["manual", "on-open", "on-open-once-per-backend"]); self.auto_latency_policy_combo.setCurrentIndex(max(0, self.auto_latency_policy_combo.findText(str(getattr(cfg, "auto_latency_policy", "manual")))))
                self.run_latency_button = QPushButton("Measure active backend latency")
                self.retest_backends_button = QPushButton("Re-test backends (fresh probe)")
                self.test_xdg_portal_button = QPushButton("Test xdg-portal")
                self.benchmark_xdg_portal_button = QPushButton("Benchmark xdg-portal")
                self.latency_label = QLabel(latency_result_summary(None))
                self.xdg_hint_label = QLabel("")

                self.hdr_transfer_combo = QComboBox(); self.hdr_transfer_combo.addItems(["srgb", "pq"]); self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))))
                self.hdr_primaries_combo = QComboBox(); self.hdr_primaries_combo.addItems(["bt709", "bt2020"]); self.hdr_primaries_combo.setCurrentIndex(max(0, self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))))
                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.hdr_max_nits_slider.setRange(HDR_MAX_NITS_MIN, HDR_MAX_NITS_MAX); self.hdr_max_nits_slider.setValue(int(getattr(cfg, "hdr_max_nits", 1000.0)))
                self.sampling_quality_combo = QComboBox(); self.sampling_quality_combo.addItems(labels(SAMPLING_QUALITY_LABELS)); self.sampling_quality_combo.setCurrentIndex(max(0, self.sampling_quality_combo.findText(label_for_value(SAMPLING_QUALITY_LABELS, str(getattr(cfg, "sampling_quality", "high")), default="High"))))
                self.performance_priority_combo = QComboBox(); self.performance_priority_combo.addItems(labels(PERFORMANCE_PRIORITY_LABELS)); self.performance_priority_combo.setCurrentIndex(max(0, self.performance_priority_combo.findText(label_for_value(PERFORMANCE_PRIORITY_LABELS, str(getattr(cfg, "performance_priority", "normal")), default="Normal"))))
                self.led_gamma_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.led_gamma_slider.setRange(100, 400); self.led_gamma_slider.setValue(int(round(getattr(cfg, "led_gamma", 1.0) * 100)))
                self.red_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.red_gain_slider.setRange(50, 150); self.red_gain_slider.setValue(int(round(getattr(cfg, "red_gain", 1.0) * 100)))
                self.green_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.green_gain_slider.setRange(50, 150); self.green_gain_slider.setValue(int(round(getattr(cfg, "green_gain", 1.0) * 100)))
                self.blue_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.blue_gain_slider.setRange(50, 150); self.blue_gain_slider.setValue(int(round(getattr(cfg, "blue_gain", 1.0) * 100)))
                self.white_balance_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.white_balance_slider.setRange(-100, 100); self.white_balance_slider.setValue(int(round(getattr(cfg, "white_balance_temperature", 0.0) * 100)))
                self.chroma_compression_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.chroma_compression_slider.setRange(0, 60); self.chroma_compression_slider.setValue(int(round(getattr(cfg, "chroma_compression", 0.0) * 100)))
                self.neutral_luminance_gain_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.neutral_luminance_gain_slider.setRange(70, 150); self.neutral_luminance_gain_slider.setValue(int(round(getattr(cfg, "neutral_luminance_gain", 1.0) * 100)))
                self.black_luminance_cutoff_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.black_luminance_cutoff_slider.setRange(0, 300); self.black_luminance_cutoff_slider.setValue(int(round(getattr(cfg, "black_luminance_cutoff", 0.0032) * 10000)))
                self.black_luminance_knee_slider = QSlider(qt["Qt"].Orientation.Horizontal); self.black_luminance_knee_slider.setRange(5, 300); self.black_luminance_knee_slider.setValue(int(round(getattr(cfg, "black_luminance_knee", 0.0024) * 10000)))
                self.reset_led_calibration_button = QPushButton("Reset calibration")
                self.reference_test_colours_button = QPushButton("Reference test colours")
                self.guided_led_calibration_button = QPushButton("Calibrate LED colour")
                self.save_led_calibration_profile_button = QPushButton("Save active calibration profile")
                self.display_configurator_button = QPushButton("Re-run Display Setup"); self.display_configurator_button.clicked.connect(self._open_configurator)
                self.open_calibration_tool_button = QPushButton("Open calibration tool"); self.open_calibration_tool_button.clicked.connect(self._open_configurator)
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
                self.export_synthetic_sampling_overlay_button = QPushButton("Export synthetic sampling test overlay")
                self.export_zone_report_button = QPushButton("Export per-zone colour report")
                self.export_latency_report_button = QPushButton("Export live latency breakdown")
                self.self_check_label = QLabel("")
                self.sampling_export_label = QLabel("")
                self.zone_report_label = QLabel("")
                self.latency_report_label = QLabel("")
                self.recovery_tools_hint_label = QLabel(
                    "Use tray Advanced / Troubleshooting for Run Doctor, Run Smoke Test, launch diagnostics, and probe cache reset."
                )
                self.preview_label = self.simple_calibration_widget.preview_text_label; self.preview_visual_label = self.simple_calibration_widget.preview_visual_label; self.test_label = QLabel("")
                self.brightness_value = QLabel(""); self.smoothing_value = QLabel(""); self.fps_value = QLabel(""); self.zone_count_value = QLabel(""); self.device_zone_count_value = QLabel(""); self.hdr_max_nits_value = QLabel(""); self.sdr_boost_nits_value = QLabel(""); self.sampling_quality_value = QLabel(""); self.smoothing_speed_value = QLabel(""); self.led_gamma_value = QLabel(""); self.red_gain_value = QLabel(""); self.green_gain_value = QLabel(""); self.blue_gain_value = QLabel(""); self.white_balance_value = QLabel(""); self.chroma_compression_value = QLabel(""); self.neutral_luminance_gain_value = QLabel(""); self.black_luminance_cutoff_value = QLabel(""); self.black_luminance_knee_value = QLabel("")
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
                    self.sampling_quality_combo.currentIndexChanged,
                    self.reverse_checkbox.stateChanged,
                    self.capture_backend_combo.currentIndexChanged,
                    self.auto_probe_policy_combo.currentIndexChanged,
                    self.display_preset_combo.currentIndexChanged,
                ):
                    signal.connect(self._refresh_preview_label)
                self.zone_count_slider.valueChanged.connect(self._on_zone_count_slider_changed)
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
                    on_flash_assigned_corners=self._send_test_pattern,
                    on_walk_strip_once=self._step_test_zone,
                )
                self.run_latency_button.clicked.connect(self._run_latency_probe_manual)
                self.retest_backends_button.clicked.connect(self._run_fresh_backend_probe)
                self._update_backend_probe_button_state()
                self.test_xdg_portal_button.clicked.connect(self._run_xdg_portal_test)
                self.benchmark_xdg_portal_button.clicked.connect(self._run_xdg_portal_benchmark)
                self.edge_locality_diagnostic_button.clicked.connect(self._run_edge_locality_diagnostic)
                self.color_accuracy_diagnostic_button.clicked.connect(self._run_color_accuracy_diagnostic)
                self.run_self_check_button.clicked.connect(self._run_self_check)
                self.capture_one_diagnostic_frame_button.clicked.connect(self._capture_one_diagnostic_frame)
                self.export_live_sampling_overlay_button.clicked.connect(self._export_live_sampling_overlay)
                self.export_synthetic_sampling_overlay_button.clicked.connect(self._export_synthetic_sampling_overlay)
                self.export_zone_report_button.clicked.connect(self._export_zone_report)
                self.export_latency_report_button.clicked.connect(self._export_latency_report)
                self.use_detected_count_button.clicked.connect(self._use_detected_strip_count)
                self.keep_configured_count_button.clicked.connect(self._keep_configured_strip_count)
                self.reset_recalibrate_button.clicked.connect(self._reset_anchors)
                self.device_model_combo.currentIndexChanged.connect(self._sync_device_model_selection)
                self.sdr_boost_nits_slider.valueChanged.connect(self._on_sdr_white_slider_changed)
                self.sdr_white_reference_preset_combo.currentIndexChanged.connect(self._on_sdr_white_preset_changed)
                self.detect_sdr_white_button.clicked.connect(self._detect_kde_sdr_white_reference)
                self.use_detected_sdr_white_button.clicked.connect(self._use_detected_sdr_white_reference)
                self.reset_led_calibration_button.clicked.connect(self._reset_led_calibration)
                self.reference_test_colours_button.clicked.connect(self._send_reference_test_colours)
                self.guided_led_calibration_button.clicked.connect(self._open_guided_led_calibration)
                self.save_led_calibration_profile_button.clicked.connect(self._save_active_led_calibration_profile)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
                buttons.accepted.connect(self._apply_settings)
                buttons.rejected.connect(self.reject)

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

                if self._view_mode == SETTINGS_VIEW_ADVANCED:
                    content_layout.addWidget(diagnostics_section)
                else:
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
                self._refresh_numeric_labels(); self._refresh_preview_label()
                self._update_latency_label_for_latest_probe_result()
                self._maybe_auto_run_latency_check()
                if initial_section:
                    self.focus_section(initial_section)

            def _apply_tooltips(self) -> None:
                self.brightness_slider.setToolTip("Overall output intensity. Lower values reduce LED brightness.")
                self.smoothing_slider.setToolTip("Blends frame-to-frame colors to reduce flicker.")
                self.smoothing_speed_slider.setToolTip("Motion response gain for smoothing. Lower values react slower (more smoothing); 0 keeps the strongest smoothing.")
                self.fps_slider.setToolTip(
                    "This is the target update rate. Actual output FPS may be lower if capture, processing, or HID output cannot keep up."
                )
                self.sampling_quality_combo.setToolTip("Low = better performance, Balanced = default, High = best visual fidelity.")
                self.performance_priority_combo.setToolTip("High priority may improve scheduling consistency. It may fail without permission. Very high is experimental.")
                self.led_gamma_slider.setToolTip("Gamma correction for LED response. 1.00 keeps output linear.")
                self.zone_count_slider.setToolTip("Number of screen sampling zones sampled from the display.")
                self.reverse_checkbox.setToolTip("Flip strip direction if the mapping appears mirrored.")
                self.display_preset_combo.setToolTip("Select SDR, HDR, or Auto display behavior.")
                self.motion_preset_combo.setToolTip(
                    "Calm: smoother fades for video and desktop. "
                    "Responsive: adaptive default for games and general use. "
                    "Dynamic: fastest response with basic flicker control."
                )
                self.color_style_combo.setToolTip(
                    "Reference: Most accurate. Preserves greys as neutral light, avoids saturation boost, turns off only for black/near-black.\n"
                    "Ambient: Recommended glow. Similar to Reference, with slightly stronger neutral brightness and smoother ambience.\n"
                    "Vivid: Richer colour response.\n"
                    "Punchy: Strong stylised colour effect."
                )
                self.edge_locality_combo.setToolTip("Tight: most accurate/least bleed. Balanced: softer ambient look. Wide: cinematic blend.")
                self.light_spread_combo.setToolTip("Neighbour blending only. Precise = least spread, Balanced = default, Soft = cinematic.")
                self.hdr_max_nits_slider.setToolTip("Reference display peak brightness for HDR tone mapping.")
                self.capture_backend_combo.setToolTip("Select auto or force a specific capture backend.")
                self.device_model_combo.setToolTip("Select your Nanoleaf USB hardware model.")
                self.device_vid_combo.setToolTip("USB vendor ID used to locate your hardware.")
                self.device_pid_combo.setToolTip("USB product ID used to locate your hardware.")
                self.auto_probe_policy_combo.setToolTip("Choose when auto-backend probing should run.")
                self.auto_latency_policy_combo.setToolTip("Automatically run latency checks on selected lifecycle events.")
                self.device_zone_count_slider.setToolTip("Configured strip zone count used for device mapping.")
                self.output_channel_order_combo.setToolTip("Set RGB byte order expected by your strip controller.")
                self.start_on_launch_checkbox.setToolTip("Start syncing automatically right after tray launch.")
                self.compositor_hdr_mode_checkbox.setToolTip("Enable compensation when KDE Plasma is running SDR content on HDR.")
                self.sdr_boost_nits_slider.setToolTip("Plasma SDR white reference in nits when compositor HDR mode is enabled.")
                self.sdr_white_reference_preset_combo.setToolTip("Preset SDR white reference levels (80/120/160/203 nits or custom).")
                self.chroma_compression_slider.setToolTip("Chroma compression: reduces LED oversaturation.")
                self.neutral_luminance_gain_slider.setToolTip("Neutral luminance: controls how bright grey/white screen areas appear on the LEDs.")
                self.black_luminance_cutoff_slider.setToolTip("Black cutoff: controls when near-black screen areas turn the LEDs off.")
                self.white_balance_slider.setToolTip("White balance: adjusts LED tint warmer/cooler.")

            def _configure_section_layout(self, layout) -> None:
                set_margins = getattr(layout, "setContentsMargins", None)
                if callable(set_margins):
                    set_margins(12, 10, 12, 12)
                set_spacing = getattr(layout, "setHorizontalSpacing", None)
                if callable(set_spacing):
                    set_spacing(14)
                set_vertical_spacing = getattr(layout, "setVerticalSpacing", None)
                if callable(set_vertical_spacing):
                    set_vertical_spacing(9)
                set_column_stretch = getattr(layout, "setColumnStretch", None)
                if callable(set_column_stretch):
                    set_column_stretch(1, 1)
                set_column_minimum_width = getattr(layout, "setColumnMinimumWidth", None)
                if callable(set_column_minimum_width):
                    set_column_minimum_width(2, 120)

            def _section_heading(self, QLabel, text: str):
                label = QLabel(text)
                set_style = getattr(label, "setStyleSheet", None)
                if callable(set_style):
                    set_style("font-weight: 600;")
                return label

            def _help_text_label(self, QLabel, text: str):
                label = QLabel(text)
                set_wrap = getattr(label, "setWordWrap", None)
                if callable(set_wrap):
                    set_wrap(True)
                return label

            def _configure_value_label(self, label) -> None:
                set_alignment = getattr(label, "setAlignment", None)
                if callable(set_alignment):
                    set_alignment(qt["Qt"].AlignmentFlag.AlignRight | qt["Qt"].AlignmentFlag.AlignVCenter)
                set_min_width = getattr(label, "setMinimumWidth", None)
                if callable(set_min_width):
                    set_min_width(86)

            def _bind_live_numeric_updates(self) -> None:
                for signal in (
                    self.brightness_slider.valueChanged,
                    self.smoothing_slider.valueChanged,
                    self.smoothing_speed_slider.valueChanged,
                    self.fps_slider.valueChanged,
                    self.zone_count_slider.valueChanged,
                    self.device_zone_count_slider.valueChanged,
                    self.hdr_max_nits_slider.valueChanged,
                    self.led_gamma_slider.valueChanged,
                    self.red_gain_slider.valueChanged,
                    self.green_gain_slider.valueChanged,
                    self.blue_gain_slider.valueChanged,
                    self.white_balance_slider.valueChanged,
                    self.chroma_compression_slider.valueChanged,
                    self.neutral_luminance_gain_slider.valueChanged,
                    self.black_luminance_cutoff_slider.valueChanged,
                    self.black_luminance_knee_slider.valueChanged,
                    self.sampling_quality_combo.currentIndexChanged,
                ):
                    signal.connect(self._refresh_numeric_labels)

            def _build_backend_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Advanced / Troubleshooting")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(self._section_heading(QLabel, "Runtime Status"), 0, 0, 1, 3)
                layout.addWidget(self.backend_info_label, 1, 0, 1, 3)
                layout.addWidget(self.diagnostics_mapping_label, 2, 0, 1, 3)
                layout.addWidget(self.hdr_colour_path_label, 3, 0, 1, 3)

                layout.addWidget(self._section_heading(QLabel, "Backend & Probing"), 4, 0, 1, 3)
                layout.addWidget(QLabel("Auto-probe policy"), 5, 0)
                layout.addWidget(self.auto_probe_policy_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Latency auto-run policy"), 6, 0)
                layout.addWidget(self.auto_latency_policy_combo, 6, 1, 1, 2)
                layout.addWidget(self.run_latency_button, 7, 0, 1, 1)
                layout.addWidget(self.retest_backends_button, 7, 1, 1, 1)
                layout.addWidget(self.test_xdg_portal_button, 7, 2, 1, 1)
                layout.addWidget(self.benchmark_xdg_portal_button, 8, 0, 1, 3)
                layout.addWidget(self.latency_label, 9, 0, 1, 3)
                layout.addWidget(self.xdg_hint_label, 10, 0, 1, 3)

                layout.addWidget(self._section_heading(QLabel, "Diagnostics Actions"), 11, 0, 1, 3)
                layout.addWidget(self.run_self_check_button, 12, 0, 1, 3)
                layout.addWidget(self.self_check_label, 13, 0, 1, 3)
                layout.addWidget(self.capture_one_diagnostic_frame_button, 14, 0, 1, 3)
                layout.addWidget(self.export_live_sampling_overlay_button, 15, 0, 1, 3)
                layout.addWidget(self.export_synthetic_sampling_overlay_button, 16, 0, 1, 3)
                layout.addWidget(self.sampling_export_label, 17, 0, 1, 3)
                layout.addWidget(self.export_zone_report_button, 18, 0, 1, 3)
                layout.addWidget(self.zone_report_label, 19, 0, 1, 3)
                layout.addWidget(self.export_latency_report_button, 20, 0, 1, 3)
                layout.addWidget(self.latency_report_label, 21, 0, 1, 3)

                layout.addWidget(self._section_heading(QLabel, "Quality Diagnostics"), 22, 0, 1, 3)
                layout.addWidget(self.edge_locality_diagnostic_button, 23, 0, 1, 3)
                layout.addWidget(self.edge_locality_diagnostic_label, 24, 0, 1, 3)
                layout.addWidget(self.color_accuracy_diagnostic_button, 25, 0, 1, 3)
                layout.addWidget(self.color_accuracy_diagnostic_label, 26, 0, 1, 3)

                layout.addWidget(self._section_heading(QLabel, "Recovery Tools"), 27, 0, 1, 3)
                layout.addWidget(self.recovery_tools_hint_label, 28, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_display_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Display & Color")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(QLabel("Display mode"), 0, 0)
                layout.addWidget(self.display_preset_combo, 0, 1, 1, 2)
                layout.addWidget(QLabel("Motion"), 1, 0)
                layout.addWidget(self.motion_preset_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Color style"), 2, 0)
                layout.addWidget(self.color_style_combo, 2, 1, 1, 2)
                layout.addWidget(self._help_text_label(QLabel, "Grey and white screen areas create neutral ambient light. Black areas turn the LEDs off."), 3, 0, 1, 3)
                layout.addWidget(QLabel("Edge locality"), 4, 0)
                layout.addWidget(self.edge_locality_combo, 4, 1, 1, 2)
                layout.addWidget(QLabel("Light spread"), 5, 0)
                layout.addWidget(self.light_spread_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Display gamut"), 6, 0)
                layout.addWidget(self.display_gamut_combo, 6, 1, 1, 2)
                hdr_advanced = QGroupBox("HDR advanced controls")
                hdr_advanced.setCheckable(True)
                hdr_advanced.setChecked(False)
                advanced_layout = QGridLayout()
                self._configure_section_layout(advanced_layout)
                advanced_layout.addWidget(self.compositor_hdr_mode_checkbox, 0, 0, 1, 3)
                advanced_layout.addWidget(QLabel("SDR white reference preset"), 1, 0)
                advanced_layout.addWidget(self.sdr_white_reference_preset_combo, 1, 1, 1, 2)
                advanced_layout.addWidget(QLabel("SDR white reference"), 2, 0)
                advanced_layout.addWidget(self.sdr_boost_nits_slider, 2, 1)
                advanced_layout.addWidget(self.sdr_boost_nits_value, 2, 2)
                advanced_layout.addWidget(self._help_text_label(QLabel, "SDR white reference controls how bright SDR/desktop content appears when HDR is enabled."), 3, 0, 1, 3)
                advanced_layout.addWidget(self.detect_sdr_white_button, 4, 0, 1, 2)
                advanced_layout.addWidget(self.use_detected_sdr_white_button, 4, 2)
                advanced_layout.addWidget(self.detected_sdr_white_label, 5, 0, 1, 3)
                advanced_layout.addWidget(self._help_text_label(QLabel, "KDE guidance: 203 nits is a useful PQ reference. 160/120 can be more comfortable. 80 nits is nominal SDR and may look dim."), 6, 0, 1, 3)
                advanced_layout.addWidget(QLabel("HDR transfer"), 7, 0)
                advanced_layout.addWidget(self.hdr_transfer_combo, 7, 1, 1, 2)
                advanced_layout.addWidget(QLabel("HDR primaries"), 8, 0)
                advanced_layout.addWidget(self.hdr_primaries_combo, 8, 1, 1, 2)
                advanced_layout.addWidget(QLabel("HDR max brightness"), 9, 0)
                advanced_layout.addWidget(self.hdr_max_nits_slider, 9, 1)
                advanced_layout.addWidget(self.hdr_max_nits_value, 9, 2)
                hdr_advanced.setLayout(advanced_layout)
                layout.addWidget(hdr_advanced, 7, 0, 1, 3)
                led_cal = QGroupBox("LED colour calibration")
                led_layout = QGridLayout()
                self._configure_section_layout(led_layout)
                led_layout.addWidget(QLabel("Red gain"), 0, 0); led_layout.addWidget(self.red_gain_slider, 0, 1); led_layout.addWidget(self.red_gain_value, 0, 2)
                led_layout.addWidget(QLabel("Green gain"), 1, 0); led_layout.addWidget(self.green_gain_slider, 1, 1); led_layout.addWidget(self.green_gain_value, 1, 2)
                led_layout.addWidget(QLabel("Blue gain"), 2, 0); led_layout.addWidget(self.blue_gain_slider, 2, 1); led_layout.addWidget(self.blue_gain_value, 2, 2)
                led_layout.addWidget(QLabel("White balance"), 3, 0); led_layout.addWidget(self.white_balance_slider, 3, 1); led_layout.addWidget(self.white_balance_value, 3, 2)
                led_layout.addWidget(QLabel("Chroma compression"), 4, 0); led_layout.addWidget(self.chroma_compression_slider, 4, 1); led_layout.addWidget(self.chroma_compression_value, 4, 2)
                led_layout.addWidget(QLabel("Neutral luminance gain"), 5, 0); led_layout.addWidget(self.neutral_luminance_gain_slider, 5, 1); led_layout.addWidget(self.neutral_luminance_gain_value, 5, 2)
                led_layout.addWidget(QLabel("Black cutoff"), 6, 0); led_layout.addWidget(self.black_luminance_cutoff_slider, 6, 1); led_layout.addWidget(self.black_luminance_cutoff_value, 6, 2)
                led_layout.addWidget(QLabel("Black knee"), 7, 0); led_layout.addWidget(self.black_luminance_knee_slider, 7, 1); led_layout.addWidget(self.black_luminance_knee_value, 7, 2)
                led_layout.addWidget(self.reset_led_calibration_button, 8, 0, 1, 1)
                led_layout.addWidget(self.reference_test_colours_button, 8, 1, 1, 1)
                led_layout.addWidget(self.guided_led_calibration_button, 8, 2, 1, 1)
                led_layout.addWidget(self.save_led_calibration_profile_button, 9, 0, 1, 3)
                led_layout.addWidget(self._help_text_label(QLabel, "Reference: Most accurate. Preserves greys as neutral light, avoids saturation boost, turns off only for black/near-black."), 10, 0, 1, 3)
                led_layout.addWidget(self._help_text_label(QLabel, "Ambient: Recommended glow. Similar to Reference, with slightly stronger neutral brightness and smoother ambience."), 11, 0, 1, 3)
                led_cal.setLayout(led_layout)
                layout.addWidget(led_cal, 8, 0, 1, 3)
                layout.addWidget(self.display_configurator_button, 9, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_runtime_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Performance")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(QLabel("Brightness"), 0, 0); layout.addWidget(self.brightness_slider, 0, 1); layout.addWidget(self.brightness_value, 0, 2)
                layout.addWidget(QLabel("Smoothing"), 1, 0); layout.addWidget(self.smoothing_slider, 1, 1); layout.addWidget(self.smoothing_value, 1, 2)
                layout.addWidget(QLabel("Smoothing speed"), 2, 0); layout.addWidget(self.smoothing_speed_slider, 2, 1); layout.addWidget(self.smoothing_speed_value, 2, 2)
                layout.addWidget(QLabel("Target capture/output FPS"), 3, 0); layout.addWidget(self.fps_slider, 3, 1); layout.addWidget(self.fps_value, 3, 2)
                layout.addWidget(QLabel("Quality"), 4, 0); layout.addWidget(self.sampling_quality_combo, 4, 1); layout.addWidget(self.sampling_quality_value, 4, 2)
                layout.addWidget(QLabel("Performance priority"), 5, 0); layout.addWidget(self.performance_priority_combo, 5, 1, 1, 2)
                layout.addWidget(QLabel("Vibrancy (LED gamma)"), 6, 0); layout.addWidget(self.led_gamma_slider, 6, 1); layout.addWidget(self.led_gamma_value, 6, 2)
                layout.addWidget(QLabel("Capture backend"), 7, 0); layout.addWidget(self.capture_backend_combo, 7, 1, 1, 2)
                group.setLayout(layout)
                return group

            def _build_zone_mapping_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Edge Mapping")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(QLabel("Screen sampling zone count"), 0, 0); layout.addWidget(self.zone_count_slider, 0, 1); layout.addWidget(self.zone_count_value, 0, 2)
                layout.addWidget(QLabel("Strip LED zone count"), 4, 0); layout.addWidget(self.device_zone_count_slider, 4, 1); layout.addWidget(self.device_zone_count_value, 4, 2)
                layout.addWidget(self.device_zone_count_status_label, 5, 0, 1, 3)
                layout.addWidget(self.strip_count_warning_label, 6, 0, 1, 3)
                layout.addWidget(self.use_detected_count_button, 7, 0)
                layout.addWidget(self.keep_configured_count_button, 7, 1, 1, 2)
                layout.addWidget(self.reset_recalibrate_button, 8, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_calibration_testing_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Calibration")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(self._help_text_label(QLabel, "Use corner calibration to map the strip to your display corners."), 0, 0, 1, 3)
                layout.addWidget(self.open_calibration_tool_button, 1, 0, 1, 3)
                layout.addWidget(self.test_label, 2, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _build_output_startup_section(self, QGroupBox, QGridLayout, QLabel):
                group = QGroupBox("Device")
                layout = QGridLayout()
                self._configure_section_layout(layout)
                layout.addWidget(QLabel("Output channel order"), 0, 0); layout.addWidget(self.output_channel_order_combo, 0, 1, 1, 2)
                layout.addWidget(QLabel("Device model"), 1, 0); layout.addWidget(self.device_model_combo, 1, 1, 1, 2)
                layout.addWidget(QLabel("Device VID"), 2, 0); layout.addWidget(self.device_vid_combo, 2, 1, 1, 2)
                layout.addWidget(QLabel("Device PID"), 3, 0); layout.addWidget(self.device_pid_combo, 3, 1, 1, 2)
                layout.addWidget(self.start_on_launch_checkbox, 4, 0, 1, 3)
                group.setLayout(layout)
                return group

            def _open_configurator(self): self._open_display_configurator = True; self.accept()
            def wants_display_configurator(self) -> bool: return bool(self._open_display_configurator)

            def _pull_state(self):
                self._state.zone_count = int(self.zone_count_slider.value()); self._state.layout_preset = "edge-weighted"; self._state.reverse_zones = bool(self.reverse_checkbox.isChecked()); self._state.device_zone_count = int(self.device_zone_count_slider.value())
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
                if str(self.sdr_white_reference_preset_combo.currentText()).strip().lower() != "custom":
                    try:
                        self._set_slider_value_safely(self.sdr_boost_nits_slider, int(str(self.sdr_white_reference_preset_combo.currentText()).split(" ", 1)[0]))
                    except (ValueError, IndexError):
                        pass
                self.brightness_value.setText(f"{self.brightness_slider.value()}%"); self.smoothing_value.setText(f"{self.smoothing_slider.value()}%"); self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}"); self.fps_value.setText(f"{self.fps_slider.value()} FPS"); self.sampling_quality_value.setText({"Low": "Better performance", "Balanced": "Default", "High": "Best visual fidelity"}.get(str(self.sampling_quality_combo.currentText()), "Default")); self.zone_count_value.setText(str(self.zone_count_slider.value())); self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits"); self.sdr_boost_nits_value.setText(f"{self.sdr_boost_nits_slider.value()} nits"); self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}"); self.red_gain_value.setText(f"{self.red_gain_slider.value()/100.0:.2f}"); self.green_gain_value.setText(f"{self.green_gain_slider.value()/100.0:.2f}"); self.blue_gain_value.setText(f"{self.blue_gain_slider.value()/100.0:.2f}"); self.white_balance_value.setText(f"{self.white_balance_slider.value()/100.0:+.2f}"); self.chroma_compression_value.setText(f"{self.chroma_compression_slider.value()/100.0:.2f}"); self.neutral_luminance_gain_value.setText(f"{self.neutral_luminance_gain_slider.value()/100.0:.2f}"); self.black_luminance_cutoff_value.setText(f"{self.black_luminance_cutoff_slider.value()/10000.0:.4f}"); self.black_luminance_knee_value.setText(f"{self.black_luminance_knee_slider.value()/10000.0:.4f}")

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
                    warnings.append("Device-reported count differs from configured count. The configured manual value is used.")
                if source != configured:
                    warnings.append("Changing strip count invalidates calibration.")
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
                self.simple_calibration_widget.corner_checklist_label.setText(
                    "Corner checklist: Top-left | Top-right | Bottom-right | Bottom-left"
                )
                assigned_count = sum(
                    1
                    for value in (
                        self._state.corner_anchor_top_left,
                        self._state.corner_anchor_top_right,
                        self._state.corner_anchor_bottom_right,
                        self._state.corner_anchor_bottom_left,
                    )
                    if int(value) >= 0
                )
                validation_status = "Complete" if assigned_count == 4 and not warnings else ("Missing corners" if assigned_count < 4 else "Out of range")
                self.simple_calibration_widget.validation_label.setText(f"Calibration: {validation_status}")
                self.simple_calibration_widget.direction_label.setText(
                    f"Direction: {'Reversed' if self._state.reverse_zones else 'Normal'}"
                )

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
                            (
                                "Live diagnostics unavailable.\nStart mirroring to measure live output FPS."
                                if not isinstance(self._runtime_status.get("_latest_frame_rgb"), np.ndarray)
                                else "Live diagnostics available from latest captured frame."
                            ),
                            *diagnostics_text_lines(status=preview_status, cfg=pending_cfg),
                        )
                    )
                )
                hdr_path = dict((self._runtime_status or {}).get("hdr_colour_path") or {})
                if not hdr_path:
                    hdr_path = {
                        "hdr_transfer": str(self.hdr_transfer_combo.currentText()),
                        "hdr_primaries": str(self.hdr_primaries_combo.currentText()),
                        "effective_sdr_boost_scalar": float(effective_sdr_boost(sdr_boost_nits=float(self.sdr_boost_nits_slider.value()))),
                        "tone_mapping_applied": False,
                        "capture_metadata_source": "unknown",
                        "assumption": "No backend metadata available; using user preset.",
                    }
                samples = [(64, 64, 64), (128, 128, 128), (255, 255, 255), (128, 110, 110)]
                style = value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient")
                ratios = []
                neutral_ok = True
                for rgb in samples:
                    styled, cap = apply_color_style_mapping_with_diagnostics(np.asarray([rgb], dtype=np.float32), color_style=style)
                    led = apply_led_calibration(styled.astype(np.float32, copy=False), LedCalibration(red_gain=self.red_gain_slider.value()/100.0, green_gain=self.green_gain_slider.value()/100.0, blue_gain=self.blue_gain_slider.value()/100.0, led_gamma=self.led_gamma_slider.value()/100.0, white_balance_temperature=self.white_balance_slider.value()/100.0, chroma_compression=self.chroma_compression_slider.value()/100.0, neutral_luminance_gain=self.neutral_luminance_gain_slider.value()/100.0, black_luminance_cutoff=self.black_luminance_cutoff_slider.value()/10000.0, black_luminance_knee=self.black_luminance_knee_slider.value()/10000.0))
                    out = np.clip(np.rint(led[0]), 0.0, 255.0).astype(np.uint8)
                    diag = color_pipeline_diagnostics(input_rgb=rgb, output_rgb=tuple(int(v) for v in out.tolist()), chroma_cap_applied=bool(cap[0]))
                    ratios.append(float(diag["chroma_ratio"]))
                    neutral_ok = neutral_ok and bool(diag["neutral_grey_preserved"])
                self.hdr_colour_path_label.setText(
                    "\n".join(
                        (
                            "HDR colour path",
                            f"active transfer/primaries: {hdr_path.get('hdr_transfer', 'unknown')} / {hdr_path.get('hdr_primaries', 'unknown')}",
                            f"compositor HDR mode: {'yes' if bool(hdr_path.get('compositor_hdr_mode', False)) else 'no'}",
                            f"SDR white reference: {self.sdr_boost_nits_slider.value()} nits ({self.sdr_white_reference_preset_combo.currentText()})",
                            f"effective SDR boost: {float(hdr_path.get('effective_sdr_boost_scalar', 1.0)):.3f}",
                            f"tone mapper: {'yes' if bool(hdr_path.get('tone_mapping_applied', False)) else 'no'}",
                            f"SDR compensation: {'yes' if bool(hdr_path.get('sdr_compensation_applied', False)) else 'no'}",
                            f"chroma ratio diagnostic: max={max(ratios):.3f}",
                            f"neutral grey verdict: {'pass' if neutral_ok else 'warn'}",
                            f"metadata source: {hdr_path.get('capture_metadata_source', 'unknown')} | assumption: {hdr_path.get('assumption', 'none')}",
                            f"warnings: {', '.join(hdr_path.get('warnings', [])) or 'none'}",
                        )
                    )
                )

            def _export_live_sampling_overlay(self) -> None:
                pending_cfg = self.updated_config()
                frame = self._runtime_status.get("_latest_frame_rgb")
                zones = self._runtime_status.get("_latest_zones_px") or []
                side_counts = tuple(int(i) for i in (self._runtime_status.get("_latest_zone_side_counts") or (0, 0, 0, 0)))
                try:
                    out = export_sampling_overlay(
                        frame=frame if isinstance(frame, np.ndarray) else None,
                        zones=zones,
                        side_counts=side_counts,
                        status=self._runtime_status,
                        cfg=pending_cfg,
                        synthetic=False,
                    )
                    self.sampling_export_label.setText(f"Live sampling overlay saved: {out}")
                except ValueError as exc:
                    self.sampling_export_label.setText(str(exc))

            def _export_synthetic_sampling_overlay(self) -> None:
                pending_cfg = self.updated_config()
                zones = self._runtime_status.get("_latest_zones_px") or []
                side_counts = tuple(int(i) for i in (self._runtime_status.get("_latest_zone_side_counts") or (0, 0, 0, 0)))
                out = export_sampling_overlay(
                    frame=None,
                    zones=zones,
                    side_counts=side_counts,
                    status=self._runtime_status,
                    cfg=pending_cfg,
                    synthetic=True,
                )
                self.sampling_export_label.setText(f"Synthetic test overlay saved: {out}")

            def _export_zone_report(self) -> None:
                rows = list(self._runtime_status.get("_latest_zone_diagnostics") or [])
                try:
                    out = export_zone_report(rows=rows)
                except ValueError as exc:
                    self.zone_report_label.setText(str(exc))
                    return
                preview = rows[:6]
                self.zone_report_label.setText(
                    "\n".join(
                        [f"Exported {len(rows)} zone rows: {out}"]
                        + [
                            f"#{r.get('zone_index')} {r.get('side')} rect={r.get('pixel_rect')} sampled={r.get('sampled_rgb')} out={r.get('final_output_rgb')} led={r.get('mapped_physical_led_index')}"
                            for r in preview
                        ]
                    )
                )

            def _export_latency_report(self) -> None:
                try:
                    out = export_latency_report(status=self._runtime_status)
                except ValueError as exc:
                    self.latency_report_label.setText(str(exc))
                    return
                self.latency_report_label.setText(f"Exported live latency stage breakdown: {out}")

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

            def _on_sdr_white_slider_changed(self, *_args) -> None:
                if str(self.sdr_white_reference_preset_combo.currentText()).strip().lower() != "custom":
                    self.sdr_white_reference_preset_combo.setCurrentIndex(4)
                self._refresh_preview_label()

            def _on_sdr_white_preset_changed(self, *_args) -> None:
                preset_text = str(self.sdr_white_reference_preset_combo.currentText()).strip().lower()
                if preset_text != "custom":
                    self._set_slider_value_safely(
                        self.sdr_boost_nits_slider,
                        int(preset_text.split(" ", 1)[0]),
                    )
                self._refresh_preview_label()

            def _detect_kde_sdr_white_reference(self) -> None:
                detected = self._runtime_status.get("detected_kde_sdr_white_nits")
                if detected is None:
                    detected = 203.0 if bool(self.compositor_hdr_mode_checkbox.isChecked()) else 80.0
                self._runtime_status["detected_kde_sdr_white_nits"] = float(detected)
                self.detected_sdr_white_label.setText(
                    f"Detected value: {float(detected):.0f} nits (not applied)"
                )

            def _use_detected_sdr_white_reference(self) -> None:
                detected = self._runtime_status.get("detected_kde_sdr_white_nits")
                if detected is None:
                    self.detected_sdr_white_label.setText("Detected value: unavailable")
                    return
                self._set_slider_value_safely(
                    self.sdr_boost_nits_slider,
                    int(round(float(detected))),
                )
                self.detected_sdr_white_label.setText(
                    f"Detected value applied: {float(detected):.0f} nits"
                )
                self._refresh_preview_label()

            def _reset_led_calibration(self) -> None:
                self._set_slider_value_safely(self.red_gain_slider, 100)
                self._set_slider_value_safely(self.green_gain_slider, 100)
                self._set_slider_value_safely(self.blue_gain_slider, 100)
                self._set_slider_value_safely(self.led_gamma_slider, 100)
                self._set_slider_value_safely(self.white_balance_slider, 0)
                self._set_slider_value_safely(self.chroma_compression_slider, 0)
                self._set_slider_value_safely(self.neutral_luminance_gain_slider, 100)
                self._set_slider_value_safely(self.black_luminance_cutoff_slider, 32)
                self._set_slider_value_safely(self.black_luminance_knee_slider, 24)
                self._refresh_preview_label()
                self._send_guided_calibration_pattern()

            def _guided_helper_adjust(self, label: str) -> None:
                if label == "Too blue":
                    self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() - 1)
                    self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() + 1)
                elif label == "Too green":
                    self._set_slider_value_safely(self.green_gain_slider, self.green_gain_slider.value() - 1)
                    self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() + 1)
                    self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
                elif label == "Too red/pink":
                    self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() - 1)
                    self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
                elif label == "Too yellow/warm":
                    self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() - 1)
                    self._set_slider_value_safely(self.green_gain_slider, self.green_gain_slider.value() - 1)
                    self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
                elif label == "Looks neutral":
                    self.color_accuracy_diagnostic_label.setText("Looks neutral: keeping current preview values.")
                self._refresh_preview_label()
                self._send_guided_calibration_pattern()

            def _save_active_led_calibration_profile(self) -> None:
                style = str(self.display_preset_combo.currentText()).strip().lower()
                target = "SDR" if style == "sdr" else "HDR"
                self.color_accuracy_diagnostic_label.setText(f"Saved active LED calibration profile for {target}.")
                self._send_guided_calibration_pattern()

            def _open_guided_led_calibration(self) -> None:
                dialog = LedColorCalibrationDialog(
                    self,
                    on_reset=self._reset_led_calibration,
                    on_helper_adjust=self._guided_helper_adjust,
                    on_save_profile=self._save_active_led_calibration_profile,
                    on_step_changed=self._on_guided_calibration_step_changed,
                    on_open=self._on_guided_calibration_opened,
                    on_close=self._on_guided_calibration_closed,
                )
                dialog.exec()

            def _on_guided_calibration_opened(self) -> None:
                self._runtime_status["_guided_calibration_step"] = 0
                self._runtime_status["_guided_locality_marker"] = 0
                self._send_guided_calibration_pattern()

            def _on_guided_calibration_step_changed(self, step: int) -> None:
                self._runtime_status["_guided_calibration_step"] = int(step)
                self._runtime_status["_guided_locality_marker"] = 0
                self._send_guided_calibration_pattern()

            def _on_guided_calibration_closed(self) -> None:
                self._runtime_status.pop("_guided_calibration_step", None)
                self._runtime_status.pop("_guided_locality_marker", None)

            def _guided_pattern_base(self, step: int) -> list[tuple[int, int, int]]:
                levels: list[list[tuple[int, int, int]]] = [
                    [(0, 0, 0), (2, 2, 2), (8, 8, 8), (16, 16, 16)],  # black / near-black
                    [(24, 24, 24), (64, 64, 64), (160, 160, 160), (255, 255, 255)],  # grey ramp
                    [(255, 0, 0)],  # red
                    [(0, 255, 0)],  # green
                    [(0, 0, 255)],  # blue
                    [(0, 255, 255), (255, 0, 255), (255, 255, 0)],  # CMY
                    [(255, 170, 32)],  # locality marker handled specially
                    [(200, 200, 200), (255, 255, 255)],  # final neutral
                ]
                return levels[max(0, min(step, len(levels) - 1))]

            def _send_guided_calibration_pattern(self) -> None:
                if self._calibration_sender is None:
                    return
                step = int(self._runtime_status.get("_guided_calibration_step", 0) or 0)
                base = self._guided_pattern_base(step)
                calibration = LedCalibration(
                    red_gain=self.red_gain_slider.value() / 100.0,
                    green_gain=self.green_gain_slider.value() / 100.0,
                    blue_gain=self.blue_gain_slider.value() / 100.0,
                    led_gamma=self.led_gamma_slider.value() / 100.0,
                    white_balance_temperature=self.white_balance_slider.value() / 100.0,
                    chroma_compression=self.chroma_compression_slider.value() / 100.0,
                    neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0,
                    black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0,
                    black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
                )
                calibrated = apply_led_calibration(np.asarray(base, dtype=np.float32), calibration)
                colors = [tuple(int(v) for v in row.tolist()) for row in np.clip(np.rint(calibrated), 0, 255).astype(np.uint8)]
                device_zones = max(1, int(self.device_zone_count_slider.value()))
                if step == 6:
                    marker = max(0, int(self._runtime_status.get("_guided_locality_marker", 0)))
                    repeated = [(0, 0, 0) for _ in range(device_zones)]
                    repeated[marker % device_zones] = colors[0]
                    self._runtime_status["_guided_locality_marker"] = marker + 1
                else:
                    repeated = [colors[i % len(colors)] for i in range(device_zones)]
                self._calibration_sender(repeated)

            def _send_reference_test_colours(self) -> None:
                if self._calibration_sender is None:
                    self.color_accuracy_diagnostic_label.setText("Reference test colours unavailable while mirroring sender is not active.")
                    return
                pattern = [
                    (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255),
                    (0, 255, 255), (255, 0, 255), (255, 255, 0), (128, 128, 128),
                ]
                self._calibration_sender(pattern)
                self.color_accuracy_diagnostic_label.setText("Reference test colours sent.")

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
                detected = int(self._state.detected_device_zone_count or 0)
                return max(MAX_ZONE_COUNT, detected + 16)

            def _on_device_zone_count_slider_changed(self, *_args) -> None:
                previous_zone_count = self._state.effective_device_zone_count()
                max_count = self._device_zone_count_max()
                requested = int(self.device_zone_count_slider.value())
                clamped = max(1, min(requested, max_count))
                if requested != clamped:
                    self._set_slider_value_safely(self.device_zone_count_slider, clamped)
                self.device_zone_count_status_label.setText(
                    "Set this to the number of physical lighting zones on your strip. This app will not auto-change this value."
                )
                if self._source_zones_locked_to_device_count:
                    self._set_slider_value_safely(self.zone_count_slider, clamped)
                self._test_step %= max(1, clamped)
                self._refresh_preview_label()

            def _use_detected_strip_count(self) -> None:
                detected = int(self._state.detected_device_zone_count or 0)
                if detected > 0:
                    self._set_slider_value_safely(self.device_zone_count_slider, detected)
                    self.strip_count_warning_label.setText(
                        "Applied reported count to manual strip count. Recalibration is required."
                    )
                    self._refresh_preview_label()

            def _keep_configured_strip_count(self) -> None:
                self.strip_count_warning_label.setText("Keeping configured strip count.")

            def _run_edge_locality_diagnostic(self) -> None:
                self._pull_state()
                result = run_edge_locality_test(
                    zone_count=max(1, int(self._state.zone_count)),
                    edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"),
                    sampling_quality=value_for_label(SAMPLING_QUALITY_LABELS, str(self.sampling_quality_combo.currentText()), default="high"),
                    motion_preset=value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"),
                    color_style=value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient"),
                )
                self.edge_locality_diagnostic_label.setText(result.summary)

            def _run_color_accuracy_diagnostic(self) -> None:
                style = value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient")
                result = run_color_accuracy_diagnostic(
                    mapper=lambda rgb: (
                        lambda styled_cap: (
                            np.clip(np.rint(apply_led_calibration(styled_cap[0].astype(np.float32), LedCalibration(red_gain=self.red_gain_slider.value()/100.0, green_gain=self.green_gain_slider.value()/100.0, blue_gain=self.blue_gain_slider.value()/100.0, led_gamma=self.led_gamma_slider.value()/100.0, white_balance_temperature=self.white_balance_slider.value()/100.0, chroma_compression=self.chroma_compression_slider.value()/100.0, neutral_luminance_gain=self.neutral_luminance_gain_slider.value()/100.0, black_luminance_cutoff=self.black_luminance_cutoff_slider.value()/10000.0, black_luminance_knee=self.black_luminance_knee_slider.value()/10000.0))[0]),0.0,255.0).astype(np.uint8),
                            bool(styled_cap[1][0]),
                        )
                    )(apply_color_style_mapping_with_diagnostics(np.asarray([rgb], dtype=np.float32), color_style=style)),
                    color_style=style,
                )
                self.color_accuracy_diagnostic_label.setText(result.summary)

            def _run_self_check(self) -> None:
                pending_cfg = self.updated_config()
                report = run_readiness_check(
                    config=pending_cfg,
                    runtime_status=self._runtime_status,
                    source_zone_count=int(self.zone_count_slider.value()),
                )
                lines = [report.status]
                for issue in report.issues:
                    lines.append(f"- {issue.fix}")
                self.self_check_label.setText("\n".join(lines))

            def _capture_one_diagnostic_frame(self) -> None:
                if self._diagnostic_capture is None:
                    self.sampling_export_label.setText("Diagnostic capture is unavailable in this context.")
                    return
                result = dict(self._diagnostic_capture() or {})
                self.sampling_export_label.setText(str(result.get("message") or "Diagnostic capture completed."))

            def _on_zone_count_slider_changed(self, *_args) -> None:
                self._source_zones_locked_to_device_count = False
                self._state.source_zones_user_configured = True
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
                probe_details = self._backend_probe_breakdown_text(selected_backend=self._active_backend())
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
                        details=f"{measured['details']}\n{probe_details}",
                    )
                    self.run_latency_button.setText("Measure active backend latency")
                else:
                    self._latest_latency = build_latency_result(
                        requested_policy=info.requested_policy,
                        selected_backend=self._active_backend(),
                        selection_source=info.source,
                        selection_reason=info.reason,
                        measured_latency_ms=0.0,
                        measurement_kind="unavailable",
                        confidence_note="Start mirroring before measuring latency.",
                        triggered_by="manual",
                        details=f"Configured frame interval: {1000.0 / max(1, int(self.fps_slider.value())):.1f} ms at {int(self.fps_slider.value())} FPS\n{probe_details}",
                    )
                    self.run_latency_button.setText("Measure active backend latency")
                self.latency_label.setText(latency_result_summary(self._latest_latency))

            def _update_backend_probe_button_state(self) -> None:
                blocked = self._backend_probe_blocked_by_runtime_state()
                self.retest_backends_button.setEnabled(not blocked)
                if blocked:
                    self.retest_backends_button.setToolTip("Stop mirroring before re-testing backends.")
                else:
                    self.retest_backends_button.setToolTip("")

            def _backend_probe_blocked_by_runtime_state(self) -> bool:
                startup_state = str(self._runtime_status.get("startup_state") or "").strip().lower()
                lifecycle_state = str(self._runtime_status.get("lifecycle_state") or "").strip().lower()
                running = bool(self._runtime_status.get("running"))
                if running:
                    return True
                if bool(self._runtime_status.get("backend_retest_blocked")):
                    return True
                blocked_states = {"starting", "running", "stopping", "waiting_for_screen_selection"}
                return startup_state in blocked_states or lifecycle_state in blocked_states

            def _run_fresh_backend_probe(self) -> None:
                if self._backend_probe_blocked_by_runtime_state():
                    self._update_backend_probe_button_state()
                    self.latency_label.setText("Stop mirroring before re-testing backends.")
                    return
                width = int(self._runtime_status.get("capture_width") or 1920)
                height = int(self._runtime_status.get("capture_height") or 1080)
                result = run_fresh_backend_probe(width=width, height=height)
                self._runtime_status["backend_probe_attempts"] = list(result.get("attempts") or [])
                selected = str(result.get("selected_backend") or "none")
                self.latency_label.setText(self._backend_probe_breakdown_text(selected_backend=selected, result_origin="manual"))

            def _run_xdg_portal_test(self) -> None:
                self.latency_label.setText(
                    "Testing xdg-portal. Approve the KDE/portal screen or window selection prompt if it appears."
                )
                try:
                    result = run_explicit_xdg_portal_probe(
                        width=int(self._runtime_status.get("capture_width") or 1920),
                        height=int(self._runtime_status.get("capture_height") or 1080),
                    )
                    self.latency_label.setText(
                        "xdg-portal explicit test:\n"
                        f"status={result.get('status')} mode={result.get('mode')} reason={result.get('reason')}\n"
                        f"last_success_stage={result.get('last_success_stage') or '-'} failing_stage={result.get('failing_stage') or '-'}\n"
                        + "\n".join(
                            f"- {row.get('stage')}: {row.get('status')} {row.get('detail') or ''}".strip()
                            for row in (result.get("stages") or [])
                            if isinstance(row, dict)
                        )
                    )
                    if str(result.get("status")) == "failed":
                        details = result.get("details") or {}
                        self.xdg_hint_label.setText(
                            "Troubleshooting hints (run manually):\n"
                            "systemctl --user status xdg-desktop-portal xdg-desktop-portal-kde pipewire wireplumber\n"
                            "journalctl --user -u xdg-desktop-portal -u xdg-desktop-portal-kde -u pipewire -u wireplumber --since \"10 minutes ago\" --no-pager\n"
                            f"Details: expected_bytes={details.get('expected_bytes')} received_bytes={details.get('received_bytes')} "
                            f"caps={details.get('caps')} size={details.get('width')}x{details.get('height')} "
                            f"timeout_s={details.get('first_frame_timeout_s')} empty_buffers={details.get('empty_buffer_count')}"
                        )
                    else:
                        self.xdg_hint_label.setText("")
                except Exception as exc:  # noqa: BLE001
                    self.latency_label.setText(f"xdg-portal test failed: {exc}")

            def _run_xdg_portal_benchmark(self) -> None:
                self.latency_label.setText(
                    "Running manual xdg-portal benchmark. This may show a portal consent prompt."
                )
                width = int(self._runtime_status.get("capture_width") or 1920)
                height = int(self._runtime_status.get("capture_height") or 1080)
                result = run_manual_portal_benchmark(width=width, height=height, samples=30)
                if str(result.get("status")) != "tested":
                    reason = str(result.get("reason") or "unknown failure")
                    self.latency_label.setText(f"Manual xdg-portal benchmark failed: {reason}")
                    return
                rows = []
                for item in list(result.get("results") or []):
                    if not isinstance(item, dict):
                        continue
                    rows.append(
                        (
                            f"- backend={item.get('backend')} target={item.get('target_capture_size')} "
                            f"actual={item.get('actual_frame_size')} format={item.get('format')} "
                            f"bytes={item.get('frame_bytes')} stride={item.get('stride')} "
                            f"median={float(item.get('median_capture_ms') or 0.0):.2f}ms "
                            f"p95={float(item.get('p95_capture_ms') or 0.0):.2f}ms "
                            f"jitter={float(item.get('jitter_ms') or 0.0):.2f}ms "
                            f"fps={float(item.get('effective_fps') or 0.0):.2f} "
                            f"empty={item.get('empty_buffers')} failed={item.get('failed_frames')} "
                            f"cpu-conv={float(item.get('cpu_conversion_median_ms') or 0.0):.2f}ms "
                            f"e2e={item.get('e2e_frame_to_hid_ms')}"
                        )
                    )
                self.latency_label.setText(
                    "Manual xdg-portal benchmark:\n"
                    f"status={result.get('status')} recommendation={result.get('recommendation')}\n"
                    + "\n".join(rows)
                )

            def _maybe_auto_run_latency_check(self):
                if should_auto_run_latency_probe(policy=str(self.auto_latency_policy_combo.currentText()), last_result=self._latest_latency, active_backend=self._active_backend()):
                    info = backend_selection_info(self._runtime_status, cfg)
                    measured = self._measured_latency_from_runtime(triggered_by="auto")
                    probe_details = self._backend_probe_breakdown_text(selected_backend=self._active_backend())
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
                            details=f"{measured['details']}\n{probe_details}",
                        )
                        self.run_latency_button.setText("Measure active backend latency")
                    else:
                        self._latest_latency = build_latency_result(
                            requested_policy=info.requested_policy,
                            selected_backend=self._active_backend(),
                            selection_source=info.source,
                            selection_reason=info.reason,
                            measured_latency_ms=0.0,
                            measurement_kind="unavailable",
                            confidence_note="Runtime has not processed frames yet.",
                            triggered_by="auto",
                            details=f"Configured frame interval: {1000.0 / max(1, int(self.fps_slider.value())):.1f} ms at {int(self.fps_slider.value())} FPS\n{probe_details}",
                        )
                        self.run_latency_button.setText("Measure active backend latency")
                    self.latency_label.setText(latency_result_summary(self._latest_latency))
                elif self._latest_latency is None:
                    self._update_latency_label_for_latest_probe_result()

            def _update_latency_label_for_latest_probe_result(self) -> None:
                selected = str(
                    self._runtime_status.get("selected_capture_backend")
                    or self._runtime_status.get("effective_capture_backend")
                    or self._runtime_status.get("cached_probe_backend")
                    or self._active_backend()
                    or "none"
                )
                self.latency_label.setText(self._backend_probe_breakdown_text(selected_backend=selected, result_origin="auto"))

            def _measured_latency_from_runtime(self, *, triggered_by: str) -> dict[str, object] | None:
                measurement = self._runtime_status.get("latency_measurement")
                if not isinstance(measurement, dict):
                    return None
                stages = measurement.get("stages")
                if not isinstance(stages, dict):
                    return None
                total_row = stages.get("actual_work_ms") if isinstance(stages.get("actual_work_ms"), dict) else {}
                gap_row = stages.get("loop_gap_ms") if isinstance(stages.get("loop_gap_ms"), dict) else {}
                sample_count = int(total_row.get("sample_count") or 0)
                if sample_count <= 0:
                    return None
                pipeline_median = float(total_row.get("median_ms") or 0.0)
                pipeline_p95 = float(total_row.get("p95_ms") or 0.0)
                pipeline_max = float(total_row.get("max_ms") or 0.0)
                cadence_median = float(gap_row.get("median_ms") or 0.0)
                cadence_p95 = float(gap_row.get("p95_ms") or 0.0)
                dropped = int(measurement.get("dropped_or_skipped_frames") or 0)
                effective_fps = float(measurement.get("effective_output_fps") or 0.0)
                return {
                    "latency_ms": pipeline_median,
                    "confidence_note": (
                        f"Measured live runtime samples (n={sample_count}, median={pipeline_median:.1f}ms, p95={pipeline_p95:.1f}ms, max={pipeline_max:.1f}ms)"
                    ),
                    "details": (
                        f"{'Manual' if triggered_by == 'manual' else 'Auto'} measured runtime work time (not cadence) | "
                        f"loop-gap median/p95={cadence_median:.1f}/{cadence_p95:.1f}ms (cadence) | "
                        f"actual-work median/p95/max={pipeline_median:.1f}/{pipeline_p95:.1f}/{pipeline_max:.1f}ms | "
                        f"effective FPS={effective_fps:.1f} | dropped/skipped={dropped} | samples={sample_count}"
                    ),
                }

            def _backend_probe_breakdown_text(self, *, selected_backend: str, result_origin: str | None = None) -> str:
                rows = self._runtime_status.get("backend_probe_attempts")
                if not isinstance(rows, list) or not rows:
                    return (
                        "Last auto-run probe result: waiting for first result.\n"
                        "Backend attempts: unavailable (probe has not yet run in this session)."
                    )
                measured_rows = 0
                formatted: list[str] = []
                cached_backend = str(self._runtime_status.get("cached_probe_backend") or "").strip()
                has_auto_rows = False
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    status = str(item.get("status") or "skipped")
                    mode = str(item.get("mode") or ("failed" if status == "failed" else "fresh-probe"))
                    has_auto_rows = has_auto_rows or mode in {"cached", "fresh-probe", "failed", "skipped-interactive", "unavailable"}
                    sample_count = int(item.get("sample_count") or 0)
                    if status == "tested" and sample_count > 0:
                        measured_rows += 1
                    normalized_item = dict(item)
                    normalized_item["mode"] = mode
                    formatted.append(f"- {format_backend_attempt_row(normalized_item)}")
                selected_line = f"Selected backend: {selected_backend}."
                if result_origin == "manual":
                    header = "Last manual probe result."
                elif result_origin == "auto":
                    header = "Last auto-run probe result." if has_auto_rows else "Last auto-run probe result: waiting for first result."
                else:
                    header = "Last probe result."
                if cached_backend and result_origin != "manual":
                    formatted.insert(
                        0,
                        f"Using cached backend: {cached_backend}. Press Re-test backends to run a fresh manual probe.",
                    )
                if measured_rows <= 0:
                    formatted.insert(0, "No measured candidate timings yet in this session.")
                elif measured_rows < 2:
                    formatted.insert(0, "Measured fewer than two candidates; backend choice may be tentative.")
                else:
                    formatted.insert(0, f"Best measured backend: {selected_backend}.")
                return f"{header}\n{selected_line}\nCandidate backends:\n" + "\n".join(formatted)

            def _apply_settings(self) -> None:
                apply_fn = self._on_apply
                if not callable(apply_fn):
                    return
                apply_fn(self.updated_config())

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
                    try:
                        vid_value = int(str(self.device_vid_combo.currentText()), 0)
                    except (ValueError, TypeError):
                        vid_value = 0x37FA
                    try:
                        pid_value = int(str(self.device_pid_combo.currentText()), 0)
                    except (ValueError, TypeError):
                        pid_value = 0x8202
                new_zones = make_edge_weighted_zones(self._state.zone_count, edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"))
                calibration_schema_version = int(getattr(cfg, "calibration_schema_version", 1) or 1)
                calibration_payload = CalibrationConfig(
                    schema_version=calibration_schema_version,
                    calibration_schema_version=calibration_schema_version,
                    calibration_model="corner_anchored",
                    device_zone_count=int(self._state.device_zone_count),
                    output_channel_order=str(self.output_channel_order_combo.currentText()),
                    reverse_zones=bool(self._state.reverse_zones),
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                )
                return replace(
                    cfg,
                    fps=int(self.fps_slider.value()), sampling_quality=str(self.sampling_quality_combo.currentText()).lower(), performance_priority=value_for_label(PERFORMANCE_PRIORITY_LABELS, str(self.performance_priority_combo.currentText()), default="normal"), brightness=self.brightness_slider.value() / 100.0,
                    smoothing=self.smoothing_slider.value() / 100.0, smoothing_speed=self.smoothing_speed_slider.value() / 100.0, led_gamma=self.led_gamma_slider.value() / 100.0,
                    red_gain=self.red_gain_slider.value() / 100.0, green_gain=self.green_gain_slider.value() / 100.0, blue_gain=self.blue_gain_slider.value() / 100.0, white_balance_temperature=self.white_balance_slider.value() / 100.0, chroma_compression=self.chroma_compression_slider.value() / 100.0, neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0, black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0, black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
                    led_calibration_profile_sdr=(
                        LedCalibrationProfile(
                            red_gain=self.red_gain_slider.value() / 100.0,
                            green_gain=self.green_gain_slider.value() / 100.0,
                            blue_gain=self.blue_gain_slider.value() / 100.0,
                            led_gamma=self.led_gamma_slider.value() / 100.0,
                            white_balance_temperature=self.white_balance_slider.value() / 100.0,
                            chroma_compression=self.chroma_compression_slider.value() / 100.0,
                            neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0,
                            black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0,
                            black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
                        )
                        if str(self.display_preset_combo.currentText()).strip().lower() == "sdr"
                        else getattr(cfg, "led_calibration_profile_sdr", LedCalibrationProfile())
                    ),
                    led_calibration_profile_hdr=(
                        LedCalibrationProfile(
                            red_gain=self.red_gain_slider.value() / 100.0,
                            green_gain=self.green_gain_slider.value() / 100.0,
                            blue_gain=self.blue_gain_slider.value() / 100.0,
                            led_gamma=self.led_gamma_slider.value() / 100.0,
                            white_balance_temperature=self.white_balance_slider.value() / 100.0,
                            chroma_compression=self.chroma_compression_slider.value() / 100.0,
                            neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0,
                            black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0,
                            black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
                        )
                        if str(self.display_preset_combo.currentText()).strip().lower() != "sdr"
                        else getattr(cfg, "led_calibration_profile_hdr", LedCalibrationProfile())
                    ),
                    zones=new_zones, layout_preset="edge-weighted", edge_locality=value_for_label(EDGE_LOCALITY_LABELS, str(self.edge_locality_combo.currentText()), default="tight"), light_spread=value_for_label(LIGHT_SPREAD_LABELS, str(self.light_spread_combo.currentText()), default="balanced"), motion_preset=value_for_label(MOTION_PRESET_LABELS, str(self.motion_preset_combo.currentText()), default="responsive"), color_style=value_for_label(COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient"), display_preset=value_for_label(DISPLAY_PRESET_LABELS, str(self.display_preset_combo.currentText()), default="hdr"),
                    start_on_launch=bool(self.start_on_launch_checkbox.isChecked()), device_zone_count=self._state.device_zone_count,
                    output_channel_order=str(self.output_channel_order_combo.currentText()), reverse_zones=self._state.reverse_zones,
                    corner_anchor_top_left=int(self._state.corner_anchor_top_left),
                    corner_anchor_top_right=int(self._state.corner_anchor_top_right),
                    corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
                    corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
                    use_mock_capture=bool(getattr(cfg, "use_mock_capture", False)), prefer_backend=str(self.capture_backend_combo.currentText()), auto_probe_policy=str(self.auto_probe_policy_combo.currentText()), auto_latency_policy=str(self.auto_latency_policy_combo.currentText()),
                    latency_last_backend=(self._latest_latency.selected_backend if self._latest_latency else getattr(cfg, "latency_last_backend", "")),
                    latency_last_value_ms=(self._latest_latency.measured_latency_ms if self._latest_latency else float(getattr(cfg, "latency_last_value_ms", 0.0))),
                    latency_last_trigger=(self._latest_latency.triggered_by if self._latest_latency else getattr(cfg, "latency_last_trigger", "")),
                    latency_last_timestamp=(self._latest_latency.recorded_at_utc if self._latest_latency else getattr(cfg, "latency_last_timestamp", "")),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()), hdr_primaries=str(self.hdr_primaries_combo.currentText()), hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    compositor_hdr_mode=bool(self.compositor_hdr_mode_checkbox.isChecked()), sdr_boost_nits=float(self.sdr_boost_nits_slider.value()), display_gamut=str(self.display_gamut_combo.currentText()).strip().lower(),
                    sdr_white_reference_preset=("custom" if str(self.sdr_white_reference_preset_combo.currentText()).strip().lower() == "custom" else str(self.sdr_boost_nits_slider.value())),
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
