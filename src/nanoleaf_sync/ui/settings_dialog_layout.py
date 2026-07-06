"""Layout builders for settings dialog sections."""

from __future__ import annotations

from nanoleaf_sync.ui.layout_helpers import mark_muted
from nanoleaf_sync.ui.settings_dialog_shared import (
    _FallbackLayout,
    _FallbackScrollArea,
    _FallbackWidget,
    _qt_widget,
)


class SettingsDialogLayoutMixin:
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
            set_column_stretch(2, 0)
        set_column_minimum_width = getattr(layout, "setColumnMinimumWidth", None)
        if callable(set_column_minimum_width):
            set_column_minimum_width(2, 120)

    def _section_heading(self, QLabel, text: str):
        label = QLabel(text)
        set_prop = getattr(label, "setProperty", None)
        if callable(set_prop):
            set_prop("heading", True)
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
            set_alignment(
                self._qt["Qt"].AlignmentFlag.AlignRight | self._qt["Qt"].AlignmentFlag.AlignVCenter
            )
        set_min_width = getattr(label, "setMinimumWidth", None)
        if callable(set_min_width):
            set_min_width(86)

    def _configure_wrapping_label(self, label) -> None:
        set_wrap = getattr(label, "setWordWrap", None)
        if callable(set_wrap):
            set_wrap(True)
        set_min_width = getattr(label, "setMinimumWidth", None)
        if callable(set_min_width):
            set_min_width(0)
        set_max_width = getattr(label, "setMaximumWidth", None)
        if callable(set_max_width):
            set_max_width(760)

    def _make_scroll_area(self):
        scroll = _qt_widget(self._qt, "QScrollArea", _FallbackScrollArea)()
        scroll.setWidgetResizable(True)
        set_policy = getattr(scroll, "setHorizontalScrollBarPolicy", None)
        if callable(set_policy):
            set_policy(self._qt["Qt"].ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _set_scroll_page(self, scroll, page) -> None:
        set_max_width = getattr(page, "setMaximumWidth", None)
        if callable(set_max_width):
            set_max_width(760)
        scroll.setWidget(page)

    def _bind_live_numeric_updates(self) -> None:
        for signal in (
            self.brightness_slider.valueChanged,
            self.smoothing_slider.valueChanged,
            self.smoothing_speed_slider.valueChanged,
            self.fps_slider.valueChanged,
            self.zone_count_slider.valueChanged,
            self.device_zone_count_slider.valueChanged,
            self.hdr_max_nits_slider.valueChanged,
            self.sampling_quality_combo.currentIndexChanged,
        ):
            signal.connect(self._refresh_numeric_labels)

    def _build_everyday_section(self, QGroupBox, QGridLayout, QLabel):
        page = _qt_widget(self._qt, "QWidget", _FallbackWidget)()
        layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()
        layout.addWidget(
            self._help_text_label(
                QLabel,
                "Recommended defaults: Auto display mode, Responsive motion, "
                "Ambient colour style. Not sure? You can change these later.",
            )
        )
        group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Everyday")
        grid = QGridLayout()
        self._configure_section_layout(grid)
        grid.addWidget(QLabel("Brightness"), 0, 0)
        grid.addWidget(self.brightness_slider, 0, 1)
        grid.addWidget(self.brightness_value, 0, 2)
        grid.addWidget(QLabel("Display mode"), 1, 0)
        grid.addWidget(self.display_preset_combo, 1, 1, 1, 2)
        grid.addWidget(QLabel("Motion"), 2, 0)
        grid.addWidget(self.motion_preset_combo, 2, 1, 1, 2)
        grid.addWidget(QLabel("Colour style"), 3, 0)
        grid.addWidget(self.color_style_combo, 3, 1, 1, 2)
        grid.addWidget(
            self._help_text_label(
                QLabel,
                "Grey and white screen areas create neutral ambient light. "
                "Black areas turn the LEDs off.",
            ),
            4,
            0,
            1,
            3,
        )
        grid.addWidget(self.start_on_launch_checkbox, 5, 0, 1, 3)
        grid.addWidget(self.four_d_sync_checkbox, 6, 0, 1, 3)
        group.setLayout(grid)
        layout.addWidget(group)
        layout.addWidget(self.reset_everyday_settings_button)
        layout.addStretch(1)
        page.setLayout(layout)
        return page

    def _build_strip_setup_section(self, QGroupBox, QGridLayout, QLabel, QScrollArea):
        del QScrollArea
        scroll = self._make_scroll_area()
        page = _qt_widget(self._qt, "QWidget", _FallbackWidget)()
        layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()
        count_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Strip LED count")
        count_layout = QGridLayout()
        self._configure_section_layout(count_layout)
        count_layout.addWidget(
            self._help_text_label(
                QLabel,
                "How many addressable lighting zones does your strip have? "
                "Set this before corner calibration.",
            ),
            0,
            0,
            1,
            3,
        )
        count_layout.addWidget(QLabel("Strip LED zone count"), 1, 0)
        count_layout.addWidget(self.device_zone_count_slider, 1, 1)
        count_layout.addWidget(self.device_zone_count_value, 1, 2)
        count_layout.addWidget(self.device_zone_count_status_label, 2, 0, 1, 3)
        count_layout.addWidget(self.strip_count_warning_label, 3, 0, 1, 3)
        count_layout.addWidget(self.use_detected_count_button, 4, 0)
        count_layout.addWidget(self.keep_configured_count_button, 4, 1, 1, 2)
        count_layout.addWidget(self.screen_zone_matched_label, 5, 0, 1, 3)
        advanced_mapping = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Advanced mapping")
        advanced_mapping.setCheckable(True)
        advanced_mapping.setChecked(False)
        advanced_layout = QGridLayout()
        self._configure_section_layout(advanced_layout)
        advanced_layout.addWidget(
            self._help_text_label(
                QLabel,
                "For edge-strip mode, screen sampling zones normally match "
                "the strip count. Change this only if you know you need "
                "a different mapping.",
            ),
            0,
            0,
            1,
            3,
        )
        advanced_layout.addWidget(QLabel("Screen sampling zone count"), 1, 0)
        advanced_layout.addWidget(self.zone_count_slider, 1, 1)
        advanced_layout.addWidget(self.zone_count_value, 1, 2)
        advanced_mapping.setLayout(advanced_layout)
        count_layout.addWidget(advanced_mapping, 6, 0, 1, 3)
        count_group.setLayout(count_layout)
        layout.addWidget(count_group)

        calibration_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Corner calibration")
        cal_layout = QGridLayout()
        self._configure_section_layout(cal_layout)
        cal_layout.addWidget(
            self._help_text_label(
                QLabel,
                "Step through the LEDs until the lit LED matches a screen corner, "
                "then assign that corner.",
            ),
            0,
            0,
            1,
            3,
        )
        row = self.simple_calibration_widget.add_to_layout(cal_layout, row=1, include_header=False)
        cal_layout.addWidget(self.test_label, row, 0, 1, 3)
        row += 1
        cal_layout.addWidget(self.reset_recalibrate_button, row, 0, 1, 3)
        row += 1
        open_wizard_button = self._qt["QPushButton"]("Open full setup wizard")
        open_wizard_button.clicked.connect(self._open_configurator)
        cal_layout.addWidget(open_wizard_button, row, 0, 1, 3)
        calibration_group.setLayout(cal_layout)
        layout.addWidget(calibration_group)
        layout.addStretch(1)
        page.setLayout(layout)
        self._set_scroll_page(scroll, page)
        return scroll

    def _build_fine_tuning_section(self, QGroupBox, QGridLayout, QLabel):
        page = _qt_widget(self._qt, "QWidget", _FallbackWidget)()
        layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()

        responsiveness = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Responsiveness")
        resp_grid = QGridLayout()
        self._configure_section_layout(resp_grid)
        resp_grid.addWidget(QLabel("Performance profile"), 0, 0)
        resp_grid.addWidget(self.performance_profile_combo, 0, 1, 1, 2)
        resp_grid.addWidget(QLabel("Quality"), 1, 0)
        resp_grid.addWidget(self.sampling_quality_combo, 1, 1)
        resp_grid.addWidget(self.sampling_quality_value, 1, 2)
        resp_grid.addWidget(QLabel("Target capture/output FPS"), 2, 0)
        resp_grid.addWidget(self.fps_slider, 2, 1)
        resp_grid.addWidget(self.fps_value, 2, 2)
        resp_grid.addWidget(QLabel("Smoothing"), 3, 0)
        resp_grid.addWidget(self.smoothing_slider, 3, 1)
        resp_grid.addWidget(self.smoothing_value, 3, 2)
        resp_grid.addWidget(QLabel("Smoothing speed"), 4, 0)
        resp_grid.addWidget(self.smoothing_speed_slider, 4, 1)
        resp_grid.addWidget(self.smoothing_speed_value, 4, 2)
        responsiveness.setLayout(resp_grid)
        layout.addWidget(responsiveness)

        look = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Look")
        look_grid = QGridLayout()
        self._configure_section_layout(look_grid)
        look_grid.addWidget(QLabel("Edge locality"), 0, 0)
        look_grid.addWidget(self.edge_locality_combo, 0, 1, 1, 2)
        look_grid.addWidget(QLabel("Light spread"), 1, 0)
        look_grid.addWidget(self.light_spread_combo, 1, 1, 1, 2)
        look_grid.addWidget(QLabel("Vibrancy (LED gamma)"), 2, 0)
        look_grid.addWidget(self.led_gamma_slider, 2, 1)
        look_grid.addWidget(self.led_gamma_value, 2, 2)
        look.setLayout(look_grid)
        layout.addWidget(look)

        advanced_perf = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Advanced performance")
        advanced_perf.setCheckable(True)
        advanced_perf.setChecked(False)
        perf_grid = QGridLayout()
        self._configure_section_layout(perf_grid)
        perf_grid.addWidget(QLabel("Performance priority"), 0, 0)
        perf_grid.addWidget(self.performance_priority_combo, 0, 1, 1, 2)
        advanced_perf.setLayout(perf_grid)
        layout.addWidget(advanced_perf)
        layout.addStretch(1)
        page.setLayout(layout)
        return page

    def _build_colour_section(self, QGroupBox, QGridLayout, QLabel):
        scroll = self._make_scroll_area()
        page = _qt_widget(self._qt, "QWidget", _FallbackWidget)()
        layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()
        group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Colour")
        grid = QGridLayout()
        self._configure_section_layout(grid)
        grid.addWidget(QLabel("Display gamut"), 0, 0)
        grid.addWidget(self.display_gamut_combo, 0, 1, 1, 2)
        hdr_advanced = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("HDR advanced controls")
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
        advanced_layout.addWidget(
            self._help_text_label(
                QLabel,
                "SDR white reference controls how bright SDR/desktop content appears "
                "when HDR is enabled.",
            ),
            3,
            0,
            1,
            3,
        )
        advanced_layout.addWidget(self.detect_sdr_white_button, 4, 0, 1, 2)
        advanced_layout.addWidget(self.use_detected_sdr_white_button, 4, 2)
        advanced_layout.addWidget(self.detected_sdr_white_label, 5, 0, 1, 3)
        advanced_layout.addWidget(
            self._help_text_label(
                QLabel,
                "KDE guidance: 203 nits is a useful PQ reference. 160/120 can be more "
                "comfortable. 80 nits is nominal SDR and may look dim.",
            ),
            6,
            0,
            1,
            3,
        )
        advanced_layout.addWidget(QLabel("HDR transfer"), 7, 0)
        advanced_layout.addWidget(self.hdr_transfer_combo, 7, 1, 1, 2)
        advanced_layout.addWidget(QLabel("HDR primaries"), 8, 0)
        advanced_layout.addWidget(self.hdr_primaries_combo, 8, 1, 1, 2)
        advanced_layout.addWidget(QLabel("HDR max brightness"), 9, 0)
        advanced_layout.addWidget(self.hdr_max_nits_slider, 9, 1)
        advanced_layout.addWidget(self.hdr_max_nits_value, 9, 2)
        hdr_advanced.setLayout(advanced_layout)
        grid.addWidget(hdr_advanced, 1, 0, 1, 3)
        group.setLayout(grid)
        layout.addWidget(group)

        led_cal = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("LED colour calibration")
        led_outer = QGridLayout()
        self._configure_section_layout(led_outer)
        led_outer.addWidget(self.colours_too_dull_button, 0, 0)
        led_outer.addWidget(self.whites_tinted_button, 0, 1)
        led_outer.addWidget(self.blacks_no_off_button, 0, 2)
        led_outer.addWidget(self.guided_led_calibration_button, 1, 0, 1, 3)
        led_outer.addWidget(self.reference_test_colours_button, 2, 0, 1, 1)
        led_outer.addWidget(self.reset_led_calibration_button, 2, 1, 1, 1)
        led_outer.addWidget(self.save_led_calibration_profile_button, 2, 2, 1, 1)
        manual_led = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Manual adjustments")
        manual_led.setCheckable(True)
        manual_led.setChecked(False)
        led_layout = QGridLayout()
        self._configure_section_layout(led_layout)
        led_layout.addWidget(QLabel("Red gain"), 0, 0)
        led_layout.addWidget(self.red_gain_slider, 0, 1)
        led_layout.addWidget(self.red_gain_value, 0, 2)
        led_layout.addWidget(QLabel("Green gain"), 1, 0)
        led_layout.addWidget(self.green_gain_slider, 1, 1)
        led_layout.addWidget(self.green_gain_value, 1, 2)
        led_layout.addWidget(QLabel("Blue gain"), 2, 0)
        led_layout.addWidget(self.blue_gain_slider, 2, 1)
        led_layout.addWidget(self.blue_gain_value, 2, 2)
        led_layout.addWidget(QLabel("White balance"), 3, 0)
        led_layout.addWidget(self.white_balance_slider, 3, 1)
        led_layout.addWidget(self.white_balance_value, 3, 2)
        led_layout.addWidget(QLabel("Chroma compression"), 4, 0)
        led_layout.addWidget(self.chroma_compression_slider, 4, 1)
        led_layout.addWidget(self.chroma_compression_value, 4, 2)
        led_layout.addWidget(QLabel("Neutral luminance gain"), 5, 0)
        led_layout.addWidget(self.neutral_luminance_gain_slider, 5, 1)
        led_layout.addWidget(self.neutral_luminance_gain_value, 5, 2)
        led_layout.addWidget(QLabel("Black cutoff"), 6, 0)
        led_layout.addWidget(self.black_luminance_cutoff_slider, 6, 1)
        led_layout.addWidget(self.black_luminance_cutoff_value, 6, 2)
        led_layout.addWidget(QLabel("Black knee"), 7, 0)
        led_layout.addWidget(self.black_luminance_knee_slider, 7, 1)
        led_layout.addWidget(self.black_luminance_knee_value, 7, 2)
        manual_led.setLayout(led_layout)
        led_outer.addWidget(manual_led, 3, 0, 1, 3)
        led_cal.setLayout(led_outer)
        layout.addWidget(led_cal)
        layout.addStretch(1)
        page.setLayout(layout)
        self._set_scroll_page(scroll, page)
        return scroll

    def _build_advanced_section(self, QGroupBox, QGridLayout, QLabel):
        scroll = self._make_scroll_area()
        page = _qt_widget(self._qt, "QWidget", _FallbackWidget)()
        layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()

        device_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("USB device")
        device_layout = QGridLayout()
        self._configure_section_layout(device_layout)
        device_layout.addWidget(QLabel("Output channel order"), 0, 0)
        device_layout.addWidget(self.output_channel_order_combo, 0, 1, 1, 2)
        device_layout.addWidget(QLabel("Device model"), 1, 0)
        device_layout.addWidget(self.device_model_combo, 1, 1, 1, 2)
        device_layout.addWidget(QLabel("Device VID"), 2, 0)
        device_layout.addWidget(self.device_vid_combo, 2, 1, 1, 2)
        device_layout.addWidget(QLabel("Device PID"), 3, 0)
        device_layout.addWidget(self.device_pid_combo, 3, 1, 1, 2)
        device_layout.addWidget(self.allow_custom_device_ids_checkbox, 4, 0, 1, 3)
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        capture_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Capture")
        capture_grid = QGridLayout()
        self._configure_section_layout(capture_grid)
        capture_grid.addWidget(QLabel("Capture backend"), 0, 0)
        capture_grid.addWidget(self.capture_backend_combo, 0, 1, 1, 2)
        capture_grid.addWidget(QLabel("Capture monitor"), 1, 0)
        capture_grid.addWidget(self.capture_monitor_edit, 1, 1, 1, 2)
        capture_monitor_hint = QLabel(
            "Choose one monitor to mirror. Multi-monitor simultaneous mirroring "
            "and multiple strips are not supported."
        )
        mark_muted(capture_monitor_hint)
        capture_grid.addWidget(capture_monitor_hint, 2, 0, 1, 3)

        runtime_status = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)(
            "Runtime status (technical)"
        )
        runtime_status.setCheckable(True)
        runtime_status.setChecked(False)
        runtime_layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()
        runtime_layout.addWidget(self.backend_info_label)
        runtime_layout.addWidget(self.diagnostics_mapping_label)
        runtime_layout.addWidget(self.hdr_colour_path_label)
        runtime_status.setLayout(runtime_layout)
        capture_grid.addWidget(runtime_status, 3, 0, 1, 3)

        capture_grid.addWidget(QLabel("Auto-probe policy"), 4, 0)
        capture_grid.addWidget(self.auto_probe_policy_combo, 4, 1, 1, 2)
        capture_grid.addWidget(QLabel("Latency auto-run policy"), 5, 0)
        capture_grid.addWidget(self.auto_latency_policy_combo, 5, 1, 1, 2)
        capture_grid.addWidget(self.run_latency_button, 6, 0)
        capture_grid.addWidget(self.retest_backends_button, 6, 1)
        capture_grid.addWidget(self.test_xdg_portal_button, 6, 2)
        capture_grid.addWidget(self.benchmark_xdg_portal_button, 7, 0, 1, 2)
        capture_grid.addWidget(self.reset_portal_screen_button, 7, 2)
        capture_grid.addWidget(self.latency_label, 8, 0, 1, 3)
        capture_grid.addWidget(self.xdg_hint_label, 9, 0, 1, 3)
        capture_group.setLayout(capture_grid)
        layout.addWidget(capture_group)

        privacy_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Privacy zones")
        privacy_grid = QGridLayout()
        self._configure_section_layout(privacy_grid)
        privacy_grid.addWidget(QLabel("Excluded regions (x, y, w, h)"), 0, 0)
        privacy_grid.addWidget(self.privacy_zone_x_edit, 0, 1)
        privacy_grid.addWidget(self.privacy_zone_y_edit, 0, 2)
        privacy_grid.addWidget(self.privacy_zone_w_edit, 0, 3)
        privacy_grid.addWidget(self.privacy_zone_h_edit, 0, 4)
        privacy_grid.addWidget(self.privacy_zone_add_button, 1, 0)
        privacy_grid.addWidget(self.privacy_zone_remove_button, 1, 1)
        privacy_grid.addWidget(self.privacy_zone_reset_button, 1, 2)
        privacy_grid.addWidget(self.privacy_zones_list, 2, 0, 1, 5)
        privacy_group.setLayout(privacy_grid)
        layout.addWidget(privacy_group)

        diagnostics_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)(
            "Diagnostics exports"
        )
        diagnostics_grid = QGridLayout()
        self._configure_section_layout(diagnostics_grid)
        diagnostics_grid.addWidget(self.run_self_check_button, 0, 0)
        diagnostics_grid.addWidget(self.capture_one_diagnostic_frame_button, 0, 1)
        diagnostics_grid.addWidget(self.export_live_sampling_overlay_button, 1, 0)
        diagnostics_grid.addWidget(self.export_synthetic_sampling_overlay_button, 1, 1)
        diagnostics_grid.addWidget(self.export_zone_report_button, 2, 0)
        diagnostics_grid.addWidget(self.export_latency_report_button, 2, 1)
        diagnostics_grid.addWidget(self.edge_locality_diagnostic_button, 3, 0)
        diagnostics_grid.addWidget(self.color_accuracy_diagnostic_button, 3, 1)
        diagnostics_grid.addWidget(self.self_check_label, 4, 0, 1, 3)
        diagnostics_grid.addWidget(self.sampling_export_label, 5, 0, 1, 3)
        diagnostics_grid.addWidget(self.zone_report_label, 6, 0, 1, 3)
        diagnostics_grid.addWidget(self.latency_report_label, 7, 0, 1, 3)
        diagnostics_grid.addWidget(self.edge_locality_diagnostic_label, 8, 0, 1, 3)
        diagnostics_grid.addWidget(self.color_accuracy_diagnostic_label, 9, 0, 1, 3)
        diagnostics_group.setLayout(diagnostics_grid)
        layout.addWidget(diagnostics_group)

        recovery_group = _qt_widget(self._qt, "QGroupBox", _FallbackWidget)("Recovery")
        recovery_layout = _qt_widget(self._qt, "QVBoxLayout", _FallbackLayout)()
        recovery_layout.addWidget(self.recovery_tools_hint_label)
        recovery_group.setLayout(recovery_layout)
        layout.addWidget(recovery_group)
        layout.addStretch(1)
        page.setLayout(layout)
        self._set_scroll_page(scroll, page)
        return scroll
