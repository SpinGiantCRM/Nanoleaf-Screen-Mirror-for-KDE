from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.calibration_resolver import CalibrationMappingSnapshot, resolve_calibration_mapping
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.ui.calibration_flow import CALIBRATION_SEQUENCE, calibration_step_by_id, derive_corner_anchor_device_indices
from nanoleaf_sync.ui.calibration_preview import CalibrationStep, calibration_test_frame, corner_anchor_steps, coverage_sanity_step, single_zone_step
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text, mapping_preview_visual


TEST_MODES: tuple[str, ...] = (
    "coverage sanity",
    "start-point identification",
    "direction walk",
    "corner+offset alignment",
    "fine offset",
)
CORNER_OFFSET_LIMIT = 24
MIN_CALIBRATION_VALIDATION_CONFIDENCE = 1.0


@dataclass
class BackendSelectionInfo:
    requested_policy: str
    selected_backend: str
    effective_backend: str
    source: str
    reason: str
    runtime_started: bool
    unresolved_reason: str


@dataclass
class TestingPanelState:
    backend_summary: str
    zone_mode_summary: str
    effective_zone_count: int
    active_test_description: str


@dataclass
class LatencyProbeResult:
    requested_policy: str
    selected_backend: str
    selection_source: str
    selection_reason: str
    measured_latency_ms: float
    measurement_kind: str  # measured | estimated
    confidence_note: str
    triggered_by: str  # manual | auto
    recorded_at_utc: str
    details: str = ""


@dataclass
class CalibrationStepProgress:
    step_id: str
    complete: bool = False
    passed: bool = False
    notes: str = ""


@dataclass
class CalibrationPhaseValidation:
    valid: bool = False
    details: str = ""


@dataclass
class CalibrationCheckpoint:
    zone_offset: int
    reverse_zones: bool
    corner_anchor_top_left: int
    corner_anchor_top_right: int
    corner_anchor_bottom_right: int
    corner_anchor_bottom_left: int
    corner_start_anchor: int
    calibration_model: str
    calibration_step_progress: dict[str, CalibrationStepProgress] = field(default_factory=dict)
    current_phase: str = ""
    phase_completion_flags: dict[str, bool] = field(default_factory=dict)
    phase_validation_state: dict[str, CalibrationPhaseValidation] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationVerificationReport:
    direction_confirmed: bool
    anchors_unique_valid: bool
    cycle_replay_confirmed: bool
    sentinel_consistency: bool
    expected_sentinels: tuple[int, ...]
    assigned_sentinels: tuple[int, ...]
    confidence_score: float
    remediation_hints: tuple[str, ...]

    def compact_summary(self) -> str:
        return (
            f"confidence={self.confidence_score:.2f} "
            f"(direction={'ok' if self.direction_confirmed else 'fix'}, "
            f"anchors={'ok' if self.anchors_unique_valid else 'fix'}, "
            f"cycle={'ok' if self.cycle_replay_confirmed else 'fix'}, "
            f"sentinel={'ok' if self.sentinel_consistency else 'fix'})"
        )


@dataclass
class CalibrationState:
    zone_count: int
    zone_preset: str
    reverse_zones: bool
    zone_offset: int
    device_zone_count: int
    explicit_zone_map: list[int] = field(default_factory=list)
    manual_mapping_enabled: bool = False
    calibration_model: str = "offset_direction"
    corner_start_anchor: int = -1
    corner_offsets_enabled: bool = False
    corner_zone_offsets: list[int] = field(default_factory=list)
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1
    calibration_step_progress: dict[str, CalibrationStepProgress] = field(default_factory=dict)
    current_phase: str = "start-point-detection"
    phase_completion_flags: dict[str, bool] = field(default_factory=dict)
    phase_validation_state: dict[str, CalibrationPhaseValidation] = field(default_factory=dict)
    checkpoint: CalibrationCheckpoint | None = None
    rollback_checkpoint: CalibrationCheckpoint | None = None
    phase_rollback_checkpoints: dict[str, CalibrationCheckpoint] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: AppConfig, runtime_status: dict | None = None) -> "CalibrationState":
        runtime_status = runtime_status or {}
        calibration = cfg.effective_calibration()
        configured_zone_count = len(cfg.zones) if cfg.zones else 0
        if configured_zone_count <= 0:
            configured_zone_count = int(getattr(calibration, "device_zone_count", 0))
        detected = int(runtime_status.get("device_zone_count") or 0)
        if configured_zone_count <= 0 and detected > 0:
            configured_zone_count = detected
        if configured_zone_count <= 0:
            configured_zone_count = 8

        explicit_zone_map = [int(i) for i in (getattr(calibration, "explicit_zone_map", []) or [])]
        anchor_values = (
            int(getattr(calibration, "corner_anchor_top_left", -1)),
            int(getattr(calibration, "corner_anchor_top_right", -1)),
            int(getattr(calibration, "corner_anchor_bottom_right", -1)),
            int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        )
        return cls(
            zone_count=max(1, int(configured_zone_count)),
            zone_preset=str(getattr(cfg, "zone_preset", "edge-weighted")),
            reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
            zone_offset=int(getattr(calibration, "zone_offset", 0)),
            device_zone_count=max(1, int(getattr(calibration, "device_zone_count", 0)) or max(1, int(configured_zone_count))),
            explicit_zone_map=explicit_zone_map,
            manual_mapping_enabled=bool(getattr(calibration, "manual_mapping_enabled", False)),
            calibration_model=str(getattr(calibration, "calibration_model", "offset_direction")),
            corner_start_anchor=int(getattr(calibration, "corner_start_anchor", -1)),
            corner_offsets_enabled=bool(getattr(calibration, "corner_offsets_enabled", False)),
            corner_zone_offsets=[int(i) for i in (getattr(calibration, "corner_zone_offsets", []) or [])][:4],
            corner_anchor_top_left=anchor_values[0],
            corner_anchor_top_right=anchor_values[1],
            corner_anchor_bottom_right=anchor_values[2],
            corner_anchor_bottom_left=anchor_values[3],
        )

    def active_corner_zone_offsets(self) -> list[int]:
        offsets = self.corner_zone_offsets[:4]
        while len(offsets) < 4:
            offsets.append(0)
        offsets = [max(-CORNER_OFFSET_LIMIT, min(CORNER_OFFSET_LIMIT, int(value))) for value in offsets]
        if not self.corner_offsets_enabled:
            return [0, 0, 0, 0]
        return offsets

    def calibration_steps(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in CALIBRATION_SEQUENCE)

    def calibration_prerequisites_met(self, step_id: str) -> bool:
        step = next((item for item in CALIBRATION_SEQUENCE if item.step_id == step_id), None)
        if step is None:
            return False
        return all(self.calibration_step_progress.get(dep, CalibrationStepProgress(step_id=dep)).passed for dep in step.prerequisites)

    def calibration_step_state(self, step_id: str) -> CalibrationStepProgress:
        existing = self.calibration_step_progress.get(step_id)
        if existing is not None:
            return existing
        created = CalibrationStepProgress(step_id=step_id)
        self.calibration_step_progress[step_id] = created
        return created

    def mark_calibration_step(self, step_id: str, *, passed: bool, notes: str = "") -> None:
        progress = self.calibration_step_state(step_id)
        progress.complete = True
        progress.passed = bool(passed)
        progress.notes = str(notes)
        self.phase_completion_flags[step_id] = bool(progress.complete)
        self.phase_validation_state[step_id] = CalibrationPhaseValidation(
            valid=bool(passed),
            details=str(notes),
        )
        self.current_phase = str(step_id)

    def evaluate_phase(self, step_id: str) -> tuple[bool, str]:
        phase = calibration_step_by_id(step_id)
        if phase is None:
            return False, "Unknown calibration phase."
        if not self.calibration_prerequisites_met(step_id):
            return False, f"Prerequisites not met for {step_id}."
        return phase.validation_fn(self, phase)

    def can_complete_calibration_flow(self) -> bool:
        for step in CALIBRATION_SEQUENCE:
            valid, details = self.evaluate_phase(step.step_id)
            self.phase_validation_state[step.step_id] = CalibrationPhaseValidation(valid=bool(valid), details=str(details))
            if not valid:
                return False
        return self.validation_report().confidence_score >= MIN_CALIBRATION_VALIDATION_CONFIDENCE

    def validation_report(self) -> CalibrationVerificationReport:
        direction_confirmed = self.calibration_step_progress.get(
            "direction-verification",
            CalibrationStepProgress(step_id="direction-verification"),
        ).passed
        cycle_replay_confirmed = self.calibration_step_progress.get(
            "validation-replay",
            CalibrationStepProgress(step_id="validation-replay"),
        ).passed
        expected = derive_corner_anchor_device_indices(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=self.explicit_zone_map if self.manual_mapping_enabled else [],
            corner_zone_offsets=self.active_corner_zone_offsets(),
            start_anchor=self.corner_start_anchor if self.corner_start_anchor >= 0 else None,
            calibration_model=self.calibration_model,
        )
        assigned = [
            int(self.corner_anchor_top_left),
            int(self.corner_anchor_top_right),
            int(self.corner_anchor_bottom_right),
            int(self.corner_anchor_bottom_left),
        ]
        has_explicit_assignments = all(value >= 0 for value in assigned)
        if not has_explicit_assignments:
            assigned = expected[:]

        anchors = {
            "top_left": assigned[0] if len(assigned) > 0 else None,
            "top_right": assigned[1] if len(assigned) > 1 else None,
            "bottom_right": assigned[2] if len(assigned) > 2 else None,
            "bottom_left": assigned[3] if len(assigned) > 3 else None,
        }
        anchor_validation = validate_corner_anchors(
            anchors=anchors,
            device_zone_count=self.effective_device_zone_count(),
        )
        anchors_unique_valid = bool(anchor_validation.valid)
        sentinel_consistency = tuple(expected[:4]) == tuple(assigned[:4])

        confidence_checks = (direction_confirmed, anchors_unique_valid, cycle_replay_confirmed)
        confidence_score = float(sum(1 for flag in confidence_checks if flag)) / float(len(confidence_checks))
        hints: list[str] = []
        if not direction_confirmed:
            hints.append("Re-run direction verification and confirm reverse/offset orientation.")
        if not anchors_unique_valid:
            hints.append("Assign four unique in-range corner anchors (TL/TR/BR/BL).")
        if not cycle_replay_confirmed:
            hints.append("Complete end-to-end validation replay for one full cycle.")
        if not sentinel_consistency:
            hints.append("Replay sentinel corners and re-assign anchors until expected and assigned corners match.")
        return CalibrationVerificationReport(
            direction_confirmed=direction_confirmed,
            anchors_unique_valid=anchors_unique_valid,
            cycle_replay_confirmed=cycle_replay_confirmed,
            sentinel_consistency=sentinel_consistency,
            expected_sentinels=tuple(expected[:4]),
            assigned_sentinels=tuple(assigned[:4]),
            confidence_score=confidence_score,
            remediation_hints=tuple(hints),
        )

    def snapshot_checkpoint(self) -> CalibrationCheckpoint:
        return CalibrationCheckpoint(
            zone_offset=int(self.zone_offset),
            reverse_zones=bool(self.reverse_zones),
            corner_anchor_top_left=int(self.corner_anchor_top_left),
            corner_anchor_top_right=int(self.corner_anchor_top_right),
            corner_anchor_bottom_right=int(self.corner_anchor_bottom_right),
            corner_anchor_bottom_left=int(self.corner_anchor_bottom_left),
            corner_start_anchor=int(self.corner_start_anchor),
            calibration_model=str(self.calibration_model),
            calibration_step_progress={
                step_id: CalibrationStepProgress(
                    step_id=progress.step_id,
                    complete=bool(progress.complete),
                    passed=bool(progress.passed),
                    notes=str(progress.notes),
                )
                for step_id, progress in self.calibration_step_progress.items()
            },
            current_phase=str(self.current_phase),
            phase_completion_flags={step_id: bool(done) for step_id, done in self.phase_completion_flags.items()},
            phase_validation_state={
                step_id: CalibrationPhaseValidation(valid=bool(state.valid), details=str(state.details))
                for step_id, state in self.phase_validation_state.items()
            },
        )

    def save_checkpoint(self) -> CalibrationCheckpoint:
        self.checkpoint = self.snapshot_checkpoint()
        self.rollback_checkpoint = self.checkpoint
        self.phase_rollback_checkpoints[self.current_phase] = self.checkpoint
        return self.checkpoint

    def restore_checkpoint(self, checkpoint: CalibrationCheckpoint | None = None) -> bool:
        target = checkpoint or self.checkpoint
        if target is None:
            return False
        self.zone_offset = int(target.zone_offset)
        self.reverse_zones = bool(target.reverse_zones)
        self.corner_anchor_top_left = int(target.corner_anchor_top_left)
        self.corner_anchor_top_right = int(target.corner_anchor_top_right)
        self.corner_anchor_bottom_right = int(target.corner_anchor_bottom_right)
        self.corner_anchor_bottom_left = int(target.corner_anchor_bottom_left)
        self.corner_start_anchor = int(target.corner_start_anchor)
        self.calibration_model = str(target.calibration_model)
        self.calibration_step_progress = {
            step_id: CalibrationStepProgress(
                step_id=progress.step_id,
                complete=bool(progress.complete),
                passed=bool(progress.passed),
                notes=str(progress.notes),
            )
            for step_id, progress in target.calibration_step_progress.items()
        }
        self.current_phase = str(target.current_phase or self.current_phase)
        self.phase_completion_flags = {step_id: bool(done) for step_id, done in target.phase_completion_flags.items()}
        self.phase_validation_state = {
            step_id: CalibrationPhaseValidation(valid=bool(state.valid), details=str(state.details))
            for step_id, state in target.phase_validation_state.items()
        }
        return True

    def save_phase_checkpoint(self, step_id: str) -> CalibrationCheckpoint:
        checkpoint = self.snapshot_checkpoint()
        self.phase_rollback_checkpoints[str(step_id)] = checkpoint
        self.rollback_checkpoint = checkpoint
        return checkpoint

    def restore_phase_checkpoint(self, step_id: str) -> bool:
        checkpoint = self.phase_rollback_checkpoints.get(str(step_id))
        if checkpoint is None:
            return False
        return self.restore_checkpoint(checkpoint)

    def auto_detection_status(self) -> str:
        return f"Using configured strip zone count {self.device_zone_count}."

    def effective_device_zone_count(self) -> int:
        return max(1, int(self.device_zone_count))

    def resolved_mapping_snapshot(self) -> CalibrationMappingSnapshot:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled and self.calibration_model != "corner_anchored" else []
        return resolve_calibration_mapping(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            manual_mapping_enabled=bool(explicit),
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model=self.calibration_model,
        )

    def mapping_preview_text(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        explicit = self.explicit_zone_map if self.manual_mapping_enabled and self.calibration_model != "corner_anchored" else []
        return (
            f"{self.auto_detection_status()}\n"
            f"Anchors TL/TR/BR/BL: {self.corner_anchor_top_left}/{self.corner_anchor_top_right}/{self.corner_anchor_bottom_right}/{self.corner_anchor_bottom_left}\n"
            f"Local corner anchor nudges (TL/TR/BR/BL): {'/'.join(f'{value:+d}' for value in self.active_corner_zone_offsets())}\n"
            f"{'Corner-anchored mapping active' if self.calibration_model == 'corner_anchored' else ('Manual mapping enabled' if self.manual_mapping_enabled else 'Corner anchors inferred from current mapping')}\n"
            f"{mapping_preview_text(zone_count=self.zone_count, device_zone_count=self.effective_device_zone_count(), zone_offset=self.zone_offset, reverse_zones=self.reverse_zones, explicit_zone_map=explicit, corner_zone_offsets=self.active_corner_zone_offsets(), corner_anchor_top_left=self.corner_anchor_top_left, corner_anchor_top_right=self.corner_anchor_top_right, corner_anchor_bottom_right=self.corner_anchor_bottom_right, corner_anchor_bottom_left=self.corner_anchor_bottom_left, calibration_model=self.calibration_model, resolved_mapping=snapshot)}"
        )

    def mapping_preview_visual(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        explicit = self.explicit_zone_map if self.manual_mapping_enabled and self.calibration_model != "corner_anchored" else []
        return mapping_preview_visual(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model=self.calibration_model,
            resolved_mapping=snapshot,
        )

    def _corner_steps(self, resolved_mapping: CalibrationMappingSnapshot | None = None) -> list[CalibrationStep]:
        snapshot = resolved_mapping or self.resolved_mapping_snapshot()
        explicit = self.explicit_zone_map if self.manual_mapping_enabled and self.calibration_model != "corner_anchored" else []
        anchors = corner_anchor_steps(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
            start_anchor=self.corner_start_anchor if self.corner_start_anchor >= 0 else None,
            calibration_model=self.calibration_model,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            resolved_mapping=snapshot.device_to_source_indices,
        )
        return anchors

    def step_for_mode(self, mode: str, step: int) -> CalibrationStep:
        snapshot = self.resolved_mapping_snapshot()
        explicit = self.explicit_zone_map if self.manual_mapping_enabled and self.calibration_model != "corner_anchored" else []
        if mode == "corner+offset alignment":
            anchors = self._corner_steps(snapshot)
            anchor = anchors[step % len(anchors)]
            return CalibrationStep(
                device_zone_index=anchor.device_zone_index,
                source_zone_index=anchor.source_zone_index,
                label=(
                    f"Corner+offset alignment | mapping zone offset={self.zone_offset:+d} | test zone step {step % len(anchors) + 1}/{len(anchors)} | reverse={'on' if self.reverse_zones else 'off'} | {anchor.label}"
                ),
            )
        if mode == "coverage sanity":
            return coverage_sanity_step(
                step=step,
                zone_count=self.zone_count,
                device_zone_count=self.effective_device_zone_count(),
                zone_offset=self.zone_offset,
                reverse_zones=self.reverse_zones,
                explicit_zone_map=explicit,
                corner_zone_offsets=self.active_corner_zone_offsets(),
                calibration_model=self.calibration_model,
                corner_anchor_top_left=self.corner_anchor_top_left,
                corner_anchor_top_right=self.corner_anchor_top_right,
                corner_anchor_bottom_right=self.corner_anchor_bottom_right,
                corner_anchor_bottom_left=self.corner_anchor_bottom_left,
                resolved_mapping=snapshot.device_to_source_indices,
            )
        prefix = "Direction walk"
        if mode == "start-point identification":
            prefix = "Start-point check"
        elif mode == "fine offset":
            prefix = "Fine offset"
        return single_zone_step(
            step=step,
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
            calibration_model=self.calibration_model,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            resolved_mapping=snapshot.device_to_source_indices,
            label_prefix=prefix,
        )

    def cycle_length(self, mode: str) -> int:
        if mode == "corner+offset alignment":
            return max(1, len(self._corner_steps()))
        return max(1, self.effective_device_zone_count())

    def frame_for_step(self, *, mode: str, step: int, brightness: float, all_off_except_active: bool) -> list[tuple[int, int, int]]:
        active_step = self.step_for_mode(mode, step)
        inactive = (0, 0, 0) if all_off_except_active else (8, 8, 8)
        return calibration_test_frame(
            device_zone_count=self.effective_device_zone_count(),
            active_indices=[active_step.device_zone_index],
            brightness=brightness,
            inactive_color=inactive,
        )


def backend_selection_info(runtime_status: dict | None, cfg: AppConfig) -> BackendSelectionInfo:
    status = runtime_status or {}
    requested = str(status.get("requested_capture_backend") or cfg.prefer_backend)
    selected_backend = str(
        status.get("selected_capture_backend")
        or status.get("effective_capture_backend")
        or status.get("capture_backend")
        or status.get("cached_probe_backend")
        or ""
    ).strip()
    running = bool(status.get("running"))
    effective = str(status.get("effective_capture_backend") or status.get("capture_backend") or "").strip()
    unresolved_reason = ""
    if effective.lower() in {"", "unknown", "auto"}:
        if not running:
            effective = "not-started"
            unresolved_reason = "Runtime has not started yet."
        elif selected_backend.lower() in {"", "unknown", "auto"}:
            effective = "unresolved"
            unresolved_reason = (
                f"No concrete backend implementation resolved from requested policy '{requested}'."
            )
        else:
            effective = selected_backend
    if selected_backend.lower() in {"", "auto"}:
        selected_backend = "unresolved"
    if requested == "auto":
        if bool(status.get("from_auto_probe")):
            source = "auto-probe"
        elif str(status.get("cached_probe_backend") or ""):
            source = "auto-cache"
        else:
            source = "auto-fallback"
    else:
        source = "manual-policy"
    reason = str(status.get("selection_reason") or "No runtime reason text available.")
    return BackendSelectionInfo(
        requested_policy=requested,
        selected_backend=selected_backend,
        effective_backend=effective,
        source=source,
        reason=reason,
        runtime_started=running,
        unresolved_reason=unresolved_reason,
    )


def build_testing_panel_state(*, state: CalibrationState, runtime_status: dict | None, cfg: AppConfig, mode: str, step: int) -> TestingPanelState:
    backend = backend_selection_info(runtime_status, cfg)
    active = state.step_for_mode(mode, step)
    return TestingPanelState(
        backend_summary=(
            f"Requested backend policy: {backend.requested_policy} | Selected backend: {backend.selected_backend} "
            f"| Effective runtime backend: {backend.effective_backend} | Source: {backend.source} | Reason: {backend.reason}"
            + (f" | Unresolved: {backend.unresolved_reason}" if backend.unresolved_reason else "")
        ),
        zone_mode_summary=(
            "Strip LED zone mode: configured"
        )
        + f" | {state.auto_detection_status()}",
        effective_zone_count=state.effective_device_zone_count(),
        active_test_description=active.label,
    )


def next_corner_start_anchor(current: int, *, device_zone_count: int) -> int:
    total = max(1, int(device_zone_count))
    return (int(current) + 1) % total


def build_latency_result(
    *,
    requested_policy: str,
    selected_backend: str,
    selection_source: str,
    selection_reason: str,
    measured_latency_ms: float,
    measurement_kind: str,
    confidence_note: str,
    triggered_by: str,
    details: str = "",
) -> LatencyProbeResult:
    return LatencyProbeResult(
        requested_policy=str(requested_policy),
        selected_backend=str(selected_backend),
        selection_source=str(selection_source),
        selection_reason=str(selection_reason),
        measured_latency_ms=float(measured_latency_ms),
        measurement_kind=str(measurement_kind),
        confidence_note=str(confidence_note),
        triggered_by=str(triggered_by),
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        details=str(details),
    )


def should_auto_run_latency_probe(*, policy: str, last_result: LatencyProbeResult | None, active_backend: str) -> bool:
    normalized = str(policy or "manual").strip().lower()
    if normalized == "manual":
        return False
    if normalized == "on-open":
        return True
    if normalized == "on-open-once-per-backend":
        if last_result is None:
            return True
        return str(last_result.selected_backend) != str(active_backend)
    return False


def latency_result_summary(result: LatencyProbeResult | None) -> str:
    if result is None:
        return "Latency checker has not been run yet."
    if result.measurement_kind == "measured":
        summary_kind = "measured pipeline latency"
    elif result.measurement_kind == "policy":
        summary_kind = "policy recommendation"
    else:
        summary_kind = "heuristic frame-interval estimate"
    return (
        f"Latest latency check: {result.measured_latency_ms:.1f} ms [{summary_kind}] | "
        f"requested_policy={result.requested_policy} | backend={result.selected_backend} | source={result.selection_source} | "
        f"trigger={result.triggered_by} | confidence={result.confidence_note} | at={result.recorded_at_utc}"
        + (f" | {result.details}" if result.details else "")
    )
