"""Settings dialog preview and calibration handlers."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
from dataclasses import replace
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.led_calibration_profile_io import (
    export_measured_led_calibration_profile,
    import_measured_led_calibration_profile,
)
from nanoleaf_sync.config.model import (
    LedCalibrationProfile,
)
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
    color_pipeline_diagnostics,
)
from nanoleaf_sync.runtime.compositor import effective_sdr_boost
from nanoleaf_sync.runtime.diagnostics_exports import (
    diagnostics_text_lines,
    export_latency_report,
    export_sampling_overlay,
    export_zone_report,
)
from nanoleaf_sync.ui.calibration_state import (
    backend_selection_info,
    build_testing_panel_state,
)
from nanoleaf_sync.ui.led_color_calibration_dialog import LedColorCalibrationDialog
from nanoleaf_sync.ui.preset_ui import (
    COLOR_STYLE_LABELS,
    DISPLAY_PRESET_LABELS,
    EDGE_LOCALITY_LABELS,
    LIGHT_SPREAD_LABELS,
    MOTION_PRESET_LABELS,
    PERFORMANCE_PROFILE_LABELS,
    SAMPLING_QUALITY_LABELS,
    label_for_value,
    value_for_label,
)
from nanoleaf_sync.ui.settings_dialog_shared import (
    CALIBRATION_MODE_PHYSICAL,
)

_log = logging.getLogger(__name__)


class SettingsDialogHandlersMixin:
    def _stop_calibration_preview_timer(self) -> None:
        stop = getattr(self._live_preview_timer, "stop", None)
        if callable(stop):
            stop()

    def reject(self) -> None:
        self._stop_calibration_preview_timer()
        baseline = getattr(self, "_baseline_config", None)
        if baseline is not None and self.updated_config() != baseline:
            box = self._qt["QMessageBox"](self)
            box.setWindowTitle("Unsaved settings")
            box.setText("Settings were changed but not saved.")
            save_btn = box.addButton("Save", self._qt["QMessageBox"].ButtonRole.AcceptRole)
            discard_btn = box.addButton(
                "Discard", self._qt["QMessageBox"].ButtonRole.DestructiveRole
            )
            box.addButton("Cancel", self._qt["QMessageBox"].ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == save_btn:
                self._apply_settings()
                super().reject()
            elif clicked == discard_btn:
                self._settings_applied_in_session = False
                super().reject()
            return
        super().reject()

    def accept(self) -> None:
        self._stop_calibration_preview_timer()
        super().accept()

    def _open_configurator(self):
        self._open_display_configurator = True
        self.accept()

    def wants_display_configurator(self) -> bool:
        return bool(self._open_display_configurator)

    def _pull_state(self):
        self._state.zone_count = int(self.zone_count_slider.value())
        self._state.reverse_zones = bool(self.reverse_checkbox.isChecked())
        self._state.device_zone_count = int(self.device_zone_count_slider.value())
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

    def _set_combo_value_safely(self, combo, options, value: str, *, default: str) -> None:
        label = label_for_value(options, value, default=default)
        idx = combo.findText(label)
        if idx < 0 or int(combo.currentIndex()) == int(idx):
            return
        block_signals = getattr(combo, "blockSignals", None)
        previous = False
        if callable(block_signals):
            previous = bool(block_signals(True))
        combo.setCurrentIndex(idx)
        if callable(block_signals):
            block_signals(previous)

    def _on_performance_profile_changed(self, *_args) -> None:
        profile = value_for_label(
            PERFORMANCE_PROFILE_LABELS,
            str(self.performance_profile_combo.currentText()),
            default="balanced",
        )
        presets = {
            "performance": {
                "fps": 30,
                "sampling_quality": "low",
                "edge_locality": "tight",
                "light_spread": "precise",
                "motion_preset": "calm",
                "smoothing": 65,
                "smoothing_speed": 60,
            },
            "balanced": {
                "fps": 60,
                "sampling_quality": "balanced",
                "edge_locality": "balanced",
                "light_spread": "balanced",
                "motion_preset": "responsive",
                "smoothing": 50,
                "smoothing_speed": 75,
            },
            "quality": {
                "fps": 60,
                "sampling_quality": "high",
                "edge_locality": "wide",
                "light_spread": "precise",
                "motion_preset": "responsive",
                "smoothing": 35,
                "smoothing_speed": 120,
            },
        }
        preset = presets.get(profile, presets["balanced"])
        self._set_slider_value_safely(self.fps_slider, int(preset["fps"]))
        self._set_slider_value_safely(self.smoothing_slider, int(preset["smoothing"]))
        self._set_slider_value_safely(self.smoothing_speed_slider, int(preset["smoothing_speed"]))
        self._set_combo_value_safely(
            self.sampling_quality_combo,
            SAMPLING_QUALITY_LABELS,
            str(preset["sampling_quality"]),
            default="Balanced",
        )
        self._set_combo_value_safely(
            self.edge_locality_combo,
            EDGE_LOCALITY_LABELS,
            str(preset["edge_locality"]),
            default="Balanced",
        )
        self._set_combo_value_safely(
            self.light_spread_combo,
            LIGHT_SPREAD_LABELS,
            str(preset["light_spread"]),
            default="Balanced",
        )
        self._set_combo_value_safely(
            self.motion_preset_combo,
            MOTION_PRESET_LABELS,
            str(preset["motion_preset"]),
            default="Responsive",
        )
        self._refresh_preview_label()

    def _refresh_numeric_labels(self):
        if str(self.sdr_white_reference_preset_combo.currentText()).strip().lower() != "custom":
            with contextlib.suppress(ValueError, IndexError):
                self._set_slider_value_safely(
                    self.sdr_boost_nits_slider,
                    int(str(self.sdr_white_reference_preset_combo.currentText()).split(" ", 1)[0]),
                )
        self.brightness_value.setText(f"{self.brightness_slider.value()}%")
        self.smoothing_value.setText(f"{self.smoothing_slider.value()}%")
        self.smoothing_speed_value.setText(f"{self.smoothing_speed_slider.value() / 100.0:.2f}")
        self.fps_value.setText(f"{self.fps_slider.value()} FPS")
        self.sampling_quality_value.setText(
            {
                "Low": "Better performance",
                "Balanced": "Default",
                "High": "Best visual fidelity",
            }.get(str(self.sampling_quality_combo.currentText()), "Default")
        )
        self.zone_count_value.setText(str(self.zone_count_slider.value()))
        self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
        self.sdr_boost_nits_value.setText(f"{self.sdr_boost_nits_slider.value()} nits")
        self.led_gamma_value.setText(f"{self.led_gamma_slider.value() / 100.0:.2f}")
        self.red_gain_value.setText(f"{self.red_gain_slider.value() / 100.0:.2f}")
        self.green_gain_value.setText(f"{self.green_gain_slider.value() / 100.0:.2f}")
        self.blue_gain_value.setText(f"{self.blue_gain_slider.value() / 100.0:.2f}")
        self.white_balance_value.setText(f"{self.white_balance_slider.value() / 100.0:+.2f}")
        self.chroma_compression_value.setText(
            f"{self.chroma_compression_slider.value() / 100.0:.2f}"
        )
        self.neutral_luminance_gain_value.setText(
            f"{self.neutral_luminance_gain_slider.value() / 100.0:.2f}"
        )
        self.black_luminance_cutoff_value.setText(
            f"{self.black_luminance_cutoff_slider.value() / 10000.0:.4f}"
        )
        self.black_luminance_knee_value.setText(
            f"{self.black_luminance_knee_slider.value() / 10000.0:.4f}"
        )

    def _schedule_refresh_preview_label(self) -> None:
        self._refresh_numeric_labels()
        self._preview_refresh_timer.start(75)

    def _refresh_preview_label(self):
        if self._preview_refresh_timer.isActive():
            self._preview_refresh_timer.stop()
        self._refresh_numeric_labels()
        self._pull_state()
        pending_cfg = replace(
            self._cfg_seed,
            prefer_backend=str(self.capture_backend_combo.currentText()),
            auto_probe_policy=str(self.auto_probe_policy_combo.currentText()),
        )
        preview_status = {
            **self._runtime_status,
            "requested_capture_backend": pending_cfg.prefer_backend,
        }
        info = backend_selection_info(preview_status, pending_cfg)
        self.backend_info_label.setText(
            f"Requested backend policy: {info.requested_policy} | "
            f"Selected backend: {info.selected_backend} | "
            f"Effective runtime backend: {info.effective_backend} | "
            f"Source: {info.source} | Reason: {info.reason}"
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
        if (
            detected > 0
            and configured != detected
            and not (
                bool(getattr(self._cfg_seed, "allow_zone_count_override", False)) and configured > 0
            )
        ):
            warnings.append(
                "Device-reported count differs from configured count. "
                "The configured manual value is used."
            )
        if source != configured:
            warnings.append("Changing strip count invalidates calibration.")
        anchors_out_of_range = anchor_max >= configured
        if anchors_out_of_range:
            warnings.append("Current anchors were assigned for a different strip length.")
        self.strip_count_warning_label.setText("\n".join(warnings))
        if self._source_zones_locked_to_device_count:
            matched = int(self.device_zone_count_slider.value())
            self.screen_zone_matched_label.setText(
                f"Screen sampling zones: {matched} (matched to strip)"
            )
        else:
            self.screen_zone_matched_label.setText(
                f"Screen sampling zones: {int(self.zone_count_slider.value())} "
                f"(custom mapping — expand Advanced mapping to edit)"
            )

        active_step = self._current_calibration_step()
        current_zone = active_step.device_zone_index
        step_total = self._test_cycle_length()
        self.current_zone_label.setText(
            f"Test zone step: {self._test_step + 1}/{step_total} | "
            f"Active physical strip zone: {current_zone}"
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
        validation_status = (
            "Complete"
            if assigned_count == 4 and not anchors_out_of_range
            else ("Missing corners" if assigned_count < 4 else "Out of range")
        )
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
                "effective_sdr_boost_scalar": float(
                    effective_sdr_boost(sdr_boost_nits=float(self.sdr_boost_nits_slider.value()))
                ),
                "tone_mapping_applied": False,
                "capture_metadata_source": "unknown",
                "assumption": "No backend metadata available; using user preset.",
            }
        samples = [(64, 64, 64), (128, 128, 128), (255, 255, 255), (128, 110, 110)]
        style = value_for_label(
            COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient"
        )
        ratios = []
        neutral_ok = True
        for rgb in samples:
            styled, cap = apply_color_style_mapping_with_diagnostics(
                np.asarray([rgb], dtype=np.float32), color_style=style
            )
            led = apply_led_calibration(
                styled.astype(np.float32, copy=False),
                LedCalibration(
                    red_gain=self.red_gain_slider.value() / 100.0,
                    green_gain=self.green_gain_slider.value() / 100.0,
                    blue_gain=self.blue_gain_slider.value() / 100.0,
                    led_gamma=self.led_gamma_slider.value() / 100.0,
                    white_balance_temperature=self.white_balance_slider.value() / 100.0,
                    chroma_compression=self.chroma_compression_slider.value() / 100.0,
                    neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0,
                    black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0,
                    black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
                ),
            )
            out = np.clip(np.rint(led[0]), 0.0, 255.0).astype(np.uint8)
            diag = color_pipeline_diagnostics(
                input_rgb=rgb,
                output_rgb=tuple(int(v) for v in out.tolist()),
                chroma_cap_applied=bool(cap[0]),
            )
            ratios.append(float(diag["chroma_ratio"]))
            neutral_ok = neutral_ok and bool(diag["neutral_grey_preserved"])
        compositor_hdr_mode = "yes" if bool(hdr_path.get("compositor_hdr_mode", False)) else "no"
        tone_mapping_applied = "yes" if bool(hdr_path.get("tone_mapping_applied", False)) else "no"
        sdr_compensation_applied = (
            "yes" if bool(hdr_path.get("sdr_compensation_applied", False)) else "no"
        )
        sdr_compensation_suppressed = (
            "yes" if bool(hdr_path.get("sdr_compensation_suppressed_for_hdr", False)) else "no"
        )
        neutral_grey_verdict = "pass" if neutral_ok else "warn"
        self.hdr_colour_path_label.setText(
            "\n".join(
                (
                    "HDR colour path",
                    f"active transfer/primaries: "
                    f"{hdr_path.get('hdr_transfer', 'unknown')} / "
                    f"{hdr_path.get('hdr_primaries', 'unknown')}",
                    f"compositor HDR mode: {compositor_hdr_mode}",
                    f"SDR white reference: {self.sdr_boost_nits_slider.value()} nits "
                    f"({self.sdr_white_reference_preset_combo.currentText()})",
                    f"effective SDR boost: "
                    f"{float(hdr_path.get('effective_sdr_boost_scalar', 1.0)):.3f}",
                    f"tone mapper: {tone_mapping_applied}",
                    f"SDR compensation: {sdr_compensation_applied}",
                    f"SDR compensation suppressed (HDR tone-map): {sdr_compensation_suppressed}",
                    f"chroma ratio diagnostic: max={max(ratios):.3f}",
                    f"neutral grey verdict: {neutral_grey_verdict}",
                    f"metadata source: "
                    f"{hdr_path.get('capture_metadata_source', 'unknown')} | "
                    f"assumption: {hdr_path.get('assumption', 'none')}",
                    f"warnings: {', '.join(hdr_path.get('warnings', [])) or 'none'}",
                )
            )
        )

    def _export_live_sampling_overlay(self) -> None:
        pending_cfg = self.updated_config()
        frame = self._runtime_status.get("_latest_frame_rgb")
        zones = self._runtime_status.get("_latest_zones_px") or []
        side_counts = tuple(
            int(i) for i in (self._runtime_status.get("_latest_zone_side_counts") or (0, 0, 0, 0))
        )
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
        side_counts = tuple(
            int(i) for i in (self._runtime_status.get("_latest_zone_side_counts") or (0, 0, 0, 0))
        )
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
                    (
                        f"#{r.get('zone_index')} {r.get('side')} "
                        f"rect={r.get('pixel_rect')} sampled={r.get('sampled_rgb')} "
                        f"out={r.get('final_output_rgb')} "
                        f"led={r.get('mapped_physical_led_index')}"
                    )
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_device_zone_slider_range()

    def _active_led_profile(self, preset: str | None = None) -> LedCalibrationProfile:
        style = str(preset or self._active_display_preset).strip().lower()
        return self._led_profile_sdr if style == "sdr" else self._led_profile_hdr

    def _led_profile_from_sliders(self) -> LedCalibrationProfile:
        return LedCalibrationProfile(
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

    def _save_slider_values_to_profile(self, preset: str | None = None) -> None:
        style = str(preset or self._active_display_preset).strip().lower()
        profile = self._led_profile_from_sliders()
        if style == "sdr":
            self._led_profile_sdr = profile
        else:
            self._led_profile_hdr = profile

    def _load_led_profile_sliders(self, preset: str) -> None:
        profile = self._active_led_profile(preset)
        self._set_slider_value_safely(
            self.led_gamma_slider, int(round(float(profile.led_gamma) * 100))
        )
        self._set_slider_value_safely(
            self.red_gain_slider, int(round(float(profile.red_gain) * 100))
        )
        self._set_slider_value_safely(
            self.green_gain_slider, int(round(float(profile.green_gain) * 100))
        )
        self._set_slider_value_safely(
            self.blue_gain_slider, int(round(float(profile.blue_gain) * 100))
        )
        self._set_slider_value_safely(
            self.white_balance_slider,
            int(round(float(profile.white_balance_temperature) * 100)),
        )
        self._set_slider_value_safely(
            self.chroma_compression_slider,
            int(round(float(profile.chroma_compression) * 100)),
        )
        self._set_slider_value_safely(
            self.neutral_luminance_gain_slider,
            int(round(float(profile.neutral_luminance_gain) * 100)),
        )
        self._set_slider_value_safely(
            self.black_luminance_cutoff_slider,
            int(round(float(profile.black_luminance_cutoff) * 10000)),
        )
        self._set_slider_value_safely(
            self.black_luminance_knee_slider,
            int(round(float(profile.black_luminance_knee) * 10000)),
        )

    def _on_display_preset_changed(self, *_args) -> None:
        previous = str(self._active_display_preset or "hdr").strip().lower()
        self._save_slider_values_to_profile(previous)
        self._active_display_preset = value_for_label(
            DISPLAY_PRESET_LABELS,
            str(self.display_preset_combo.currentText()),
            default="hdr",
        )
        if self._active_display_preset == "hdr":
            self.hdr_transfer_combo.setCurrentIndex(max(0, self.hdr_transfer_combo.findText("pq")))
            self.hdr_primaries_combo.setCurrentIndex(
                max(0, self.hdr_primaries_combo.findText("bt2020"))
            )
        elif self._active_display_preset == "sdr":
            self.hdr_transfer_combo.setCurrentIndex(
                max(0, self.hdr_transfer_combo.findText("srgb"))
            )
            self.hdr_primaries_combo.setCurrentIndex(
                max(0, self.hdr_primaries_combo.findText("bt709"))
            )
        self._load_led_profile_sliders(self._active_display_preset)
        self._refresh_preview_label()

    def _on_device_usb_id_edited(self, *_args) -> None:
        if self._syncing_device_model:
            return
        self._device_ids_manual = True
        custom_index = self.device_model_combo.findText("Custom VID/PID")
        if custom_index >= 0:
            self._syncing_device_model = True
            self.device_model_combo.setCurrentIndex(custom_index)
            self._syncing_device_model = False

    def _sync_device_model_selection(self):
        if self._syncing_device_model:
            return
        selected_model = str(self.device_model_combo.currentText())
        if selected_model.startswith("Custom"):
            return
        if self._device_ids_manual:
            custom_index = self.device_model_combo.findText("Custom VID/PID")
            if custom_index >= 0:
                self._syncing_device_model = True
                self.device_model_combo.setCurrentIndex(custom_index)
                self._syncing_device_model = False
            return
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
            with contextlib.suppress(ValueError, IndexError):
                self._set_slider_value_safely(
                    self.sdr_boost_nits_slider,
                    int(preset_text.split(" ", 1)[0]),
                )
        self._refresh_preview_label()

    def _detect_kde_sdr_white_reference(self) -> None:
        detected = self._runtime_status.get("detected_kde_sdr_white_nits")
        if detected is None:
            detected = 203.0 if bool(self.compositor_hdr_mode_checkbox.isChecked()) else 80.0
        self._probe_session_state["detected_kde_sdr_white_nits"] = float(detected)
        self.detected_sdr_white_label.setText(
            f"Detected value: {float(detected):.0f} nits (not applied)"
        )

    def _use_detected_sdr_white_reference(self) -> None:
        detected = self._probe_session_state.get("detected_kde_sdr_white_nits")
        if detected is None:
            detected = self._runtime_status.get("detected_kde_sdr_white_nits")
        if detected is None:
            self.detected_sdr_white_label.setText("Detected value: unavailable")
            return
        self._set_slider_value_safely(
            self.sdr_boost_nits_slider,
            int(round(float(detected))),
        )
        self.detected_sdr_white_label.setText(f"Detected value applied: {float(detected):.0f} nits")
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
            self._set_slider_value_safely(
                self.green_gain_slider, self.green_gain_slider.value() - 1
            )
            self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() + 1)
            self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
        elif label == "Too red/pink":
            self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() - 1)
            self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
        elif label == "Too yellow/warm":
            self._set_slider_value_safely(self.red_gain_slider, self.red_gain_slider.value() - 1)
            self._set_slider_value_safely(
                self.green_gain_slider, self.green_gain_slider.value() - 1
            )
            self._set_slider_value_safely(self.blue_gain_slider, self.blue_gain_slider.value() + 1)
        elif label == "Looks neutral":
            self.color_accuracy_diagnostic_label.setText(
                "Looks neutral: keeping current preview values."
            )
        self._refresh_preview_label()
        self._send_guided_calibration_pattern()

    def _save_active_led_calibration_profile(self) -> None:
        self._save_slider_values_to_profile()
        style = str(self.display_preset_combo.currentText()).strip().lower()
        target = "SDR" if style == "sdr" else "HDR"
        self.color_accuracy_diagnostic_label.setText(
            f"Saved active LED calibration profile for {target}."
        )
        self._send_guided_calibration_pattern()

    def _active_led_profile(self, preset: str | None = None) -> LedCalibrationProfile:
        active = str(preset or self._active_display_preset or "sdr").strip().lower()
        if active == "hdr":
            return self._led_profile_hdr
        return self._led_profile_sdr

    def _export_led_calibration_profile(self) -> None:
        self._save_slider_values_to_profile()
        qt = self._qt
        QFileDialog = self._qt["QFileDialog"]
        preset = str(self._active_display_preset or "sdr").strip().lower()
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export measured LED calibration profile",
            f"nanoleaf-led-profile-{preset}.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        payload = export_measured_led_calibration_profile(
            profile=self._active_led_profile(),
            display_preset=preset,
        )
        Path(path).write_text(payload, encoding="utf-8")
        self.color_accuracy_diagnostic_label.setText(
            f"Exported measured LED calibration profile to {path}."
        )

    def _import_led_calibration_profile(self) -> None:
        qt = self._qt
        QFileDialog = self._qt["QFileDialog"]
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import measured LED calibration profile",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            preset, profile = import_measured_led_calibration_profile(
                Path(path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.color_accuracy_diagnostic_label.setText(f"Import failed: {exc}")
            return
        if preset == "hdr":
            self._led_profile_hdr = copy.deepcopy(profile)
        else:
            self._led_profile_sdr = copy.deepcopy(profile)
        self._active_display_preset = preset
        self._load_led_profile_sliders(preset)
        self._refresh_numeric_labels()
        self._refresh_preview_label()
        self.color_accuracy_diagnostic_label.setText(
            f"Imported measured LED calibration profile for {preset.upper()} from {path}."
        )

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
        colors = [
            tuple(int(v) for v in row.tolist())
            for row in np.clip(np.rint(calibrated), 0, 255).astype(np.uint8)
        ]
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
            self.color_accuracy_diagnostic_label.setText(
                "Reference test colours unavailable while mirroring sender is not active."
            )
            return
        pattern = [
            (255, 255, 255),
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (0, 255, 255),
            (255, 0, 255),
            (255, 255, 0),
            (128, 128, 128),
        ]
        device_zones = max(1, int(self.device_zone_count_slider.value()))
        repeated = [pattern[i % len(pattern)] for i in range(device_zones)]
        self._calibration_sender(repeated)
        self.color_accuracy_diagnostic_label.setText("Reference test colours sent.")
