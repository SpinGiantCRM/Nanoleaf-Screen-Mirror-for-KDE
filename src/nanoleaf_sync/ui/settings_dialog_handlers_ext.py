"""Settings dialog persistence and probe handlers."""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import replace

import numpy as np

from nanoleaf_sync.capture.factory import (
    run_explicit_xdg_portal_probe,
    run_fresh_backend_probe,
    run_manual_portal_benchmark,
)
from nanoleaf_sync.config.model import (
    MAX_DEVICE_ZONE_COUNT,
    AppConfig,
    CalibrationConfig,
)
from nanoleaf_sync.runtime.color_accuracy_diagnostics import run_color_accuracy_diagnostic
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping_with_diagnostics,
    apply_led_calibration,
)
from nanoleaf_sync.runtime.diagnostics_exports import (
    format_backend_attempt_row,
)
from nanoleaf_sync.runtime.edge_locality_diagnostics import run_edge_locality_test
from nanoleaf_sync.runtime.readiness_check import run_readiness_check
from nanoleaf_sync.ui.calibration_state import (
    backend_selection_info,
    build_latency_result,
    latency_result_summary,
    should_auto_run_latency_probe,
)
from nanoleaf_sync.ui.preset_ui import (
    COLOR_STYLE_LABELS,
    DISPLAY_PRESET_LABELS,
    EDGE_LOCALITY_LABELS,
    LIGHT_SPREAD_LABELS,
    MOTION_PRESET_LABELS,
    PERFORMANCE_PRIORITY_LABELS,
    PERFORMANCE_PROFILE_LABELS,
    SAMPLING_QUALITY_LABELS,
    value_for_label,
)
from nanoleaf_sync.ui.settings_dialog_shared import (
    _LEGACY_SECTION_ALIASES,
    CALIBRATION_MODE_PHYSICAL,
    SETTINGS_SECTIONS,
)
from nanoleaf_sync.ui.zone_presets import edge_weighted_layout, make_edge_weighted_zones

_log = logging.getLogger(__name__)


class SettingsDialogHandlersExtMixin:
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
        self._refresh_preview_label()
        self._schedule_live_preview()

    def _reset_anchors(self):
        self._state.corner_anchor_top_left = -1
        self._state.corner_anchor_top_right = -1
        self._state.corner_anchor_bottom_right = -1
        self._state.corner_anchor_bottom_left = -1
        self._refresh_preview_label()
        self._schedule_live_preview()

    def _current_calibration_step(self):
        self._test_step %= self._test_cycle_length()
        return self._state.step_for_mode(CALIBRATION_MODE_PHYSICAL, self._test_step)

    def _test_cycle_length(self):
        return self._state.cycle_length(CALIBRATION_MODE_PHYSICAL)

    def _step_test_zone(self):
        self._test_step = (self._test_step + 1) % self._test_cycle_length()
        self._refresh_preview_label()
        self._send_test_pattern()

    def _prev_test_zone(self):
        self._test_step = (self._test_step - 1) % self._test_cycle_length()
        self._refresh_preview_label()
        self._send_test_pattern()

    def _on_calibration_controls_changed(self):
        self._refresh_preview_label()
        self._schedule_live_preview()

    def _schedule_live_preview(self):
        if self._calibration_sender is None:
            return
        self._live_preview_timer.start(50)

    def _flush_live_preview(self):
        self._live_preview_timer.stop()
        self._send_test_pattern()

    def _send_test_pattern(self):
        if self._calibration_sender is None:
            return
        self._pull_state()
        # Normalize self._test_step before generating the frame.
        self._current_calibration_step()
        colors = self._state.frame_for_step(
            mode=CALIBRATION_MODE_PHYSICAL,
            step=self._test_step,
            brightness=1.0,
            all_off_except_active=True,
        )
        self._calibration_sender(colors)

    def _device_zone_count_max(self) -> int:
        detected = int(self._state.detected_device_zone_count or 0)
        return max(MAX_DEVICE_ZONE_COUNT, detected + 16)

    def _refresh_device_zone_slider_range(self) -> None:
        max_count = self._device_zone_count_max()
        self.device_zone_count_slider.setRange(1, max_count)
        if self.device_zone_count_slider.value() > max_count:
            self._set_slider_value_safely(self.device_zone_count_slider, max_count)

    def _on_device_zone_count_slider_changed(self, *_args) -> None:
        self._state.effective_device_zone_count()
        max_count = self._device_zone_count_max()
        requested = int(self.device_zone_count_slider.value())
        clamped = max(1, min(requested, max_count))
        if requested != clamped:
            self._set_slider_value_safely(self.device_zone_count_slider, clamped)
        self.device_zone_count_status_label.setText(
            "Set this to the number of physical lighting zones on your strip. "
            "This app will not auto-change this value."
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
            edge_locality=value_for_label(
                EDGE_LOCALITY_LABELS,
                str(self.edge_locality_combo.currentText()),
                default="tight",
            ),
            sampling_quality=value_for_label(
                SAMPLING_QUALITY_LABELS,
                str(self.sampling_quality_combo.currentText()),
                default="high",
            ),
            motion_preset=value_for_label(
                MOTION_PRESET_LABELS,
                str(self.motion_preset_combo.currentText()),
                default="responsive",
            ),
            color_style=value_for_label(
                COLOR_STYLE_LABELS,
                str(self.color_style_combo.currentText()),
                default="ambient",
            ),
        )
        self.edge_locality_diagnostic_label.setText(result.summary)

    def _run_color_accuracy_diagnostic(self) -> None:
        style = value_for_label(
            COLOR_STYLE_LABELS, str(self.color_style_combo.currentText()), default="ambient"
        )
        result = run_color_accuracy_diagnostic(
            mapper=lambda rgb: (
                lambda styled_cap: (
                    np.clip(
                        np.rint(
                            apply_led_calibration(
                                styled_cap[0].astype(np.float32),
                                LedCalibration(
                                    red_gain=self.red_gain_slider.value() / 100.0,
                                    green_gain=self.green_gain_slider.value() / 100.0,
                                    blue_gain=self.blue_gain_slider.value() / 100.0,
                                    led_gamma=self.led_gamma_slider.value() / 100.0,
                                    white_balance_temperature=self.white_balance_slider.value()
                                    / 100.0,
                                    chroma_compression=self.chroma_compression_slider.value()
                                    / 100.0,
                                    neutral_luminance_gain=self.neutral_luminance_gain_slider.value()
                                    / 100.0,
                                    black_luminance_cutoff=self.black_luminance_cutoff_slider.value()
                                    / 10000.0,
                                    black_luminance_knee=self.black_luminance_knee_slider.value()
                                    / 10000.0,
                                ),
                            )[0]
                        ),
                        0.0,
                        255.0,
                    ).astype(np.uint8),
                    bool(styled_cap[1][0]),
                )
            )(
                apply_color_style_mapping_with_diagnostics(
                    np.asarray([rgb], dtype=np.float32), color_style=style
                )
            ),
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
        self.sampling_export_label.setText(
            str(result.get("message") or "Diagnostic capture completed.")
        )

    def _on_zone_count_slider_changed(self, *_args) -> None:
        self._source_zones_locked_to_device_count = False
        self._state.source_zones_user_configured = True
        self._refresh_preview_label()

    def _active_backend(self) -> str:
        preview_status = {
            **(self._runtime_status or {}),
            "requested_capture_backend": str(self.capture_backend_combo.currentText()),
        }
        info = backend_selection_info(preview_status, self._cfg_seed)
        if info.effective_backend in {"not-started", "unresolved"}:
            return info.selected_backend
        return info.effective_backend

    def _run_latency_probe_manual(self):
        info = backend_selection_info(self._runtime_status, self._cfg_seed)
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
                details=(
                    f"Configured frame interval: "
                    f"{1000.0 / max(1, int(self.fps_slider.value())):.1f} ms at "
                    f"{int(self.fps_slider.value())} FPS\n{probe_details}"
                ),
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
        if self._backend_probe_running:
            return
        if self._backend_probe_blocked_by_runtime_state():
            self._update_backend_probe_button_state()
            self.latency_label.setText("Stop mirroring before re-testing backends.")
            return
        width = int(self._runtime_status.get("capture_width") or 1920)
        height = int(self._runtime_status.get("capture_height") or 1080)
        self._backend_probe_running = True
        self.retest_backends_button.setEnabled(False)
        self.latency_label.setText("Running backend probe…")

        def worker() -> None:
            try:
                result = run_fresh_backend_probe(width=width, height=height)
            except Exception as exc:  # noqa: BLE001
                result = {"selected_backend": "none", "attempts": [], "error": str(exc)}
            self.QTimer.singleShot(0, lambda: self._finish_backend_probe(result))

        threading.Thread(target=worker, daemon=True, name="backend-probe").start()

    def _finish_backend_probe(self, result: dict[str, object]) -> None:
        self._backend_probe_running = False
        self._probe_session_state["backend_probe_attempts"] = list(result.get("attempts") or [])
        selected = str(result.get("selected_backend") or "none")
        if result.get("error"):
            self.latency_label.setText(f"Backend probe failed: {result.get('error')}")
        else:
            self.latency_label.setText(
                self._backend_probe_breakdown_text(
                    selected_backend=selected, result_origin="manual"
                )
            )
        self._update_backend_probe_button_state()

    def _run_xdg_portal_test(self) -> None:
        self.latency_label.setText(
            "Testing xdg-portal. Approve the KDE/portal screen or window selection "
            "prompt if it appears."
        )
        try:
            result = run_explicit_xdg_portal_probe(
                width=int(self._runtime_status.get("capture_width") or 1920),
                height=int(self._runtime_status.get("capture_height") or 1080),
            )
            self.latency_label.setText(
                "xdg-portal explicit test:\n"
                f"status={result.get('status')} mode={result.get('mode')} "
                f"reason={result.get('reason')}\n"
                f"last_success_stage={result.get('last_success_stage') or '-'} "
                f"failing_stage={result.get('failing_stage') or '-'}\n"
                + "\n".join(
                    (f"- {row.get('stage')}: {row.get('status')} {row.get('detail') or ''}").strip()
                    for row in (result.get("stages") or [])
                    if isinstance(row, dict)
                )
            )
            if str(result.get("status")) == "failed":
                details = result.get("details") or {}
                self.xdg_hint_label.setText(
                    "Troubleshooting hints (run manually):\n"
                    "systemctl --user status xdg-desktop-portal "
                    "xdg-desktop-portal-kde pipewire wireplumber\n"
                    "journalctl --user -u xdg-desktop-portal -u xdg-desktop-portal-kde "
                    '-u pipewire -u wireplumber --since "10 minutes ago" --no-pager\n'
                    f"Details: expected_bytes={details.get('expected_bytes')} "
                    f"received_bytes={details.get('received_bytes')} "
                    f"caps={details.get('caps')} size={details.get('width')}x"
                    f"{details.get('height')} "
                    f"timeout_s={details.get('first_frame_timeout_s')} "
                    f"empty_buffers={details.get('empty_buffer_count')}"
                )
            else:
                self.xdg_hint_label.setText("")
        except Exception as exc:  # noqa: BLE001
            self.latency_label.setText(f"xdg-portal test failed: {exc}")

    def _reset_portal_screen_selection(self) -> None:
        fn = getattr(self, "_forget_portal_token_fn", None)
        if not callable(fn):
            self.latency_label.setText("Portal reset unavailable in this settings session.")
            return
        result = fn()
        message = str(result.get("message") or "Portal screen selection reset.")
        self.latency_label.setText(message)

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
                f"- backend={item.get('backend')} "
                f"target={item.get('target_capture_size')} "
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
        self.latency_label.setText(
            "Manual xdg-portal benchmark:\n"
            f"status={result.get('status')} recommendation={result.get('recommendation')}\n"
            + "\n".join(rows)
        )

    def _maybe_auto_run_latency_check(self):
        if should_auto_run_latency_probe(
            policy=str(self.auto_latency_policy_combo.currentText()),
            last_result=self._latest_latency,
            active_backend=self._active_backend(),
        ):
            info = backend_selection_info(self._runtime_status, self._cfg_seed)
            measured = self._measured_latency_from_runtime(triggered_by="auto")
            probe_details = self._backend_probe_breakdown_text(
                selected_backend=self._active_backend()
            )
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
                    details=(
                        f"Configured frame interval: "
                        f"{1000.0 / max(1, int(self.fps_slider.value())):.1f} ms at "
                        f"{int(self.fps_slider.value())} FPS\n{probe_details}"
                    ),
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
        self.latency_label.setText(
            self._backend_probe_breakdown_text(selected_backend=selected, result_origin="auto")
        )

    def _measured_latency_from_runtime(self, *, triggered_by: str) -> dict[str, object] | None:
        measurement = self._runtime_status.get("latency_measurement")
        if not isinstance(measurement, dict):
            return None
        stages = measurement.get("stages")
        if not isinstance(stages, dict):
            return None
        total_row = (
            stages.get("actual_work_ms") if isinstance(stages.get("actual_work_ms"), dict) else {}
        )
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
                f"Measured live runtime samples (n={sample_count}, "
                f"median={pipeline_median:.1f}ms, p95={pipeline_p95:.1f}ms, "
                f"max={pipeline_max:.1f}ms)"
            ),
            "details": (
                f"{'Manual' if triggered_by == 'manual' else 'Auto'} measured runtime "
                f"work time (not cadence) | "
                f"loop-gap median/p95={cadence_median:.1f}/{cadence_p95:.1f}ms (cadence) | "
                f"actual-work median/p95/max="
                f"{pipeline_median:.1f}/{pipeline_p95:.1f}/{pipeline_max:.1f}ms | "
                f"effective FPS={effective_fps:.1f} | "
                f"dropped/skipped={dropped} | samples={sample_count}"
            ),
        }

    def _backend_probe_breakdown_text(
        self, *, selected_backend: str, result_origin: str | None = None
    ) -> str:
        rows = self._probe_session_state.get("backend_probe_attempts")
        if rows is None:
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
            has_auto_rows = has_auto_rows or mode in {
                "cached",
                "fresh-probe",
                "failed",
                "skipped-interactive",
                "unavailable",
            }
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
            header = (
                "Last auto-run probe result."
                if has_auto_rows
                else "Last auto-run probe result: waiting for first result."
            )
        else:
            header = "Last probe result."
        if cached_backend and result_origin != "manual":
            formatted.insert(
                0,
                f"Using cached backend: {cached_backend}. "
                "Press Re-test backends to run a fresh manual probe.",
            )
        if measured_rows <= 0:
            formatted.insert(0, "No measured candidate timings yet in this session.")
        elif measured_rows < 2:
            formatted.insert(
                0, "Measured fewer than two candidates; backend choice may be tentative."
            )
        else:
            formatted.insert(0, f"Best measured backend: {selected_backend}.")
        return f"{header}\n{selected_line}\nCandidate backends:\n" + "\n".join(formatted)

    def _apply_settings(self) -> None:
        apply_fn = self._on_apply
        if not callable(apply_fn):
            return
        updated = self.updated_config()
        apply_fn(updated)
        self._baseline_config = updated
        self._settings_applied_in_session = True

    def settings_applied_in_session(self) -> bool:
        return bool(self._settings_applied_in_session)

    def _walk_strip_once(self) -> None:
        self._test_step = 0
        self._refresh_preview_label()
        self._send_test_pattern()

    def focus_section(self, section_name: str) -> bool:
        resolved = _LEGACY_SECTION_ALIASES.get(section_name, section_name)
        try:
            idx = SETTINGS_SECTIONS.index(resolved)
        except ValueError:
            return False
        stack = self._section_stack
        nav = self._section_nav
        if stack is not None:
            stack.setCurrentIndex(idx)
        if nav is not None:
            nav.setCurrentRow(idx)
        return True

    def updated_config(self) -> AppConfig:
        self._pull_state()
        self._save_slider_values_to_profile()
        selected_model = str(self.device_model_combo.currentText())
        if not self._device_ids_manual and selected_model.startswith("NL82K2"):
            vid_value = 0x37FA
            pid_value = 0x8202
        elif not self._device_ids_manual and selected_model.startswith("NL82K1"):
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
        new_edge_locality = value_for_label(
            EDGE_LOCALITY_LABELS,
            str(self.edge_locality_combo.currentText()),
            default="balanced",
        )
        zone_count = int(self._state.zone_count)
        layout_changed = (
            zone_count != len(self._cfg_seed.zones)
            or new_edge_locality != str(getattr(self._cfg_seed, "edge_locality", "balanced"))
            or str(getattr(self._cfg_seed, "layout_preset", "edge_strip")) != "edge_strip"
        )
        if layout_changed or not self._cfg_seed.zones:
            layout = edge_weighted_layout(
                zone_count=zone_count,
                edge_locality=new_edge_locality,
            )
            new_zones = make_edge_weighted_zones(
                zone_count,
                edge_locality=new_edge_locality,
            )
            source_side_counts = [int(v) for v in layout.side_counts]
        else:
            new_zones = list(self._cfg_seed.zones)
            source_side_counts = [
                int(v) for v in (getattr(self._cfg_seed, "source_side_counts", None) or [])
            ]
        calibration_schema_version = int(
            getattr(self._cfg_seed, "calibration_schema_version", 1) or 1
        )
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
            self._cfg_seed,
            fps=int(self.fps_slider.value()),
            sampling_quality=value_for_label(
                SAMPLING_QUALITY_LABELS,
                str(self.sampling_quality_combo.currentText()),
                default="balanced",
            ),
            performance_profile=value_for_label(
                PERFORMANCE_PROFILE_LABELS,
                str(self.performance_profile_combo.currentText()),
                default="balanced",
            ),
            performance_priority=value_for_label(
                PERFORMANCE_PRIORITY_LABELS,
                str(self.performance_priority_combo.currentText()),
                default="normal",
            ),
            brightness=self.brightness_slider.value() / 100.0,
            smoothing=self.smoothing_slider.value() / 100.0,
            smoothing_speed=self.smoothing_speed_slider.value() / 100.0,
            led_gamma=self.led_gamma_slider.value() / 100.0,
            red_gain=self.red_gain_slider.value() / 100.0,
            green_gain=self.green_gain_slider.value() / 100.0,
            blue_gain=self.blue_gain_slider.value() / 100.0,
            white_balance_temperature=self.white_balance_slider.value() / 100.0,
            chroma_compression=self.chroma_compression_slider.value() / 100.0,
            neutral_luminance_gain=self.neutral_luminance_gain_slider.value() / 100.0,
            black_luminance_cutoff=self.black_luminance_cutoff_slider.value() / 10000.0,
            black_luminance_knee=self.black_luminance_knee_slider.value() / 10000.0,
            led_calibration_profile_sdr=copy.deepcopy(self._led_profile_sdr),
            led_calibration_profile_hdr=copy.deepcopy(self._led_profile_hdr),
            zones=new_zones,
            source_side_counts=source_side_counts,
            layout_preset=str(getattr(self._cfg_seed, "layout_preset", "edge_strip")),
            edge_locality=new_edge_locality,
            light_spread=value_for_label(
                LIGHT_SPREAD_LABELS,
                str(self.light_spread_combo.currentText()),
                default="balanced",
            ),
            motion_preset=value_for_label(
                MOTION_PRESET_LABELS,
                str(self.motion_preset_combo.currentText()),
                default="responsive",
            ),
            color_style=value_for_label(
                COLOR_STYLE_LABELS,
                str(self.color_style_combo.currentText()),
                default="ambient",
            ),
            display_preset=value_for_label(
                DISPLAY_PRESET_LABELS,
                str(self.display_preset_combo.currentText()),
                default="hdr",
            ),
            start_on_launch=bool(self.start_on_launch_checkbox.isChecked()),
            sync_mode="4d" if self.four_d_sync_checkbox.isChecked() else "standard",
            device_zone_count=self._state.device_zone_count,
            output_channel_order=str(self.output_channel_order_combo.currentText()),
            reverse_zones=self._state.reverse_zones,
            corner_anchor_top_left=int(self._state.corner_anchor_top_left),
            corner_anchor_top_right=int(self._state.corner_anchor_top_right),
            corner_anchor_bottom_right=int(self._state.corner_anchor_bottom_right),
            corner_anchor_bottom_left=int(self._state.corner_anchor_bottom_left),
            use_mock_capture=(
                False
                if bool(getattr(self._cfg_seed, "wizard_completed", False))
                else bool(getattr(self._cfg_seed, "use_mock_capture", False))
            ),
            prefer_backend=str(self.capture_backend_combo.currentText()),
            capture_monitor=str(self.capture_monitor_edit.text() or "").strip(),
            auto_probe_policy=str(self.auto_probe_policy_combo.currentText()),
            auto_latency_policy=str(self.auto_latency_policy_combo.currentText()),
            latency_last_backend=(
                self._latest_latency.selected_backend
                if self._latest_latency
                else getattr(self._cfg_seed, "latency_last_backend", "")
            ),
            latency_last_value_ms=(
                self._latest_latency.measured_latency_ms
                if self._latest_latency
                else float(getattr(self._cfg_seed, "latency_last_value_ms", 0.0))
            ),
            latency_last_trigger=(
                self._latest_latency.triggered_by
                if self._latest_latency
                else getattr(self._cfg_seed, "latency_last_trigger", "")
            ),
            latency_last_timestamp=(
                self._latest_latency.recorded_at_utc
                if self._latest_latency
                else getattr(self._cfg_seed, "latency_last_timestamp", "")
            ),
            hdr_transfer=str(self.hdr_transfer_combo.currentText()),
            hdr_primaries=str(self.hdr_primaries_combo.currentText()),
            hdr_max_nits=float(self.hdr_max_nits_slider.value()),
            compositor_hdr_mode=bool(self.compositor_hdr_mode_checkbox.isChecked()),
            sdr_boost_nits=float(self.sdr_boost_nits_slider.value()),
            display_gamut=str(self.display_gamut_combo.currentText()).strip().lower(),
            sdr_white_reference_preset=(
                "custom"
                if str(self.sdr_white_reference_preset_combo.currentText()).strip().lower()
                == "custom"
                else str(self.sdr_boost_nits_slider.value())
            ),
            device_vid=int(vid_value),
            device_pid=int(pid_value),
            allow_custom_device_ids=bool(self.allow_custom_device_ids_checkbox.isChecked()),
            calibration_schema_version=calibration_schema_version,
            calibration_model="corner_anchored",
            calibration=calibration_payload,
        )
