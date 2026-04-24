from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.runtime.calibration_resolver import CalibrationMappingSnapshot, resolve_calibration_mapping
from nanoleaf_sync.ui.calibration_preview import (
    CalibrationStep,
    calibration_test_frame,
    corner_anchor_steps,
    coverage_sanity_step,
    single_zone_step,
)
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text, mapping_preview_visual

logger = logging.getLogger(__name__)

CORNER_OFFSET_LIMIT = 24


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


@dataclass(frozen=True)
class CalibrationVerificationReport:
    outcome_status: str
    direction_confirmed: bool
    anchors_unique_valid: bool
    cycle_replay_confirmed: bool
    sentinel_consistency: bool
    expected_sentinels: tuple[int, ...]
    assigned_sentinels: tuple[int, ...]
    direction_confidence_component: float
    anchors_confidence_component: float
    cycle_confidence_component: float
    confidence_score: float
    hard_fail: bool
    remediation_action: str
    remediation_hints: tuple[str, ...]

    def compact_summary(self) -> str:
        return (
            f"verification={self.outcome_status} confidence={self.confidence_score:.2f} "
            f"(direction={'ok' if self.direction_confirmed else 'fix'}, "
            f"anchors={'ok' if self.anchors_unique_valid else 'fix'}, "
            f"cycle={'ok' if self.cycle_replay_confirmed else 'fix'}, "
            f"sentinel={'ok' if self.sentinel_consistency else 'fix'})"
        )


@dataclass
class CalibrationState:
    # Active/simple state
    zone_count: int
    zone_preset: str
    reverse_zones: bool
    zone_offset: int
    device_zone_count: int
    current_test_step: int = 0
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1
    detected_device_zone_count: int = 0

    # Retained as inert/compatibility-only fields for old callers.
    explicit_zone_map: list[int] = field(default_factory=list)
    manual_mapping_enabled: bool = False
    calibration_model: str = "corner_anchored"
    corner_start_anchor: int = -1
    corner_offsets_enabled: bool = False
    corner_zone_offsets: list[int] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: AppConfig, runtime_status: dict | None = None) -> "CalibrationState":
        runtime_status = runtime_status or {}
        calibration = cfg.effective_calibration()
        source_zone_count = len(cfg.zones) if cfg.zones else 0
        configured_device_zone_count = int(getattr(calibration, "device_zone_count", 0))
        if configured_device_zone_count <= 0:
            configured_device_zone_count = int(getattr(cfg, "device_zone_count", 0))
        detected = int(runtime_status.get("device_zone_count") or 0)
        if configured_device_zone_count <= 0 and detected > 0:
            configured_device_zone_count = detected
        if source_zone_count <= 0:
            source_zone_count = configured_device_zone_count
        if source_zone_count <= 0:
            source_zone_count = 8
        if configured_device_zone_count <= 0:
            configured_device_zone_count = max(1, int(source_zone_count))

        return cls(
            zone_count=max(1, int(source_zone_count)),
            zone_preset=str(getattr(cfg, "zone_preset", "edge-weighted")),
            reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
            zone_offset=int(getattr(calibration, "zone_offset", 0)),
            device_zone_count=max(1, int(configured_device_zone_count)),
            corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
            corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
            corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
            corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
            detected_device_zone_count=detected if detected > 0 else 0,
            explicit_zone_map=[int(i) for i in (getattr(calibration, "explicit_zone_map", []) or [])],
            manual_mapping_enabled=bool(getattr(calibration, "manual_mapping_enabled", False)),
            calibration_model="corner_anchored",
            corner_start_anchor=int(getattr(calibration, "corner_start_anchor", -1)),
            corner_offsets_enabled=bool(getattr(calibration, "corner_offsets_enabled", False)),
            corner_zone_offsets=[int(i) for i in (getattr(calibration, "corner_zone_offsets", []) or [])][:4],
        )

    def active_corner_zone_offsets(self) -> list[int]:
        # Minimal active model does not use per-corner nudges.
        return [0, 0, 0, 0]

    def validation_report(self) -> CalibrationVerificationReport:
        anchors = {
            "top_left": self.corner_anchor_top_left if self.corner_anchor_top_left >= 0 else None,
            "top_right": self.corner_anchor_top_right if self.corner_anchor_top_right >= 0 else None,
            "bottom_right": self.corner_anchor_bottom_right if self.corner_anchor_bottom_right >= 0 else None,
            "bottom_left": self.corner_anchor_bottom_left if self.corner_anchor_bottom_left >= 0 else None,
        }
        anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=self.effective_device_zone_count())
        anchors_unique_valid = bool(anchor_validation.valid)
        score = 1.0 if anchors_unique_valid else 0.0
        hints = () if anchors_unique_valid else ("Assign four unique in-range corner anchors (TL/TR/BR/BL).",)
        return CalibrationVerificationReport(
            outcome_status="pass" if anchors_unique_valid else "fail",
            direction_confirmed=True,
            anchors_unique_valid=anchors_unique_valid,
            cycle_replay_confirmed=True,
            sentinel_consistency=True,
            expected_sentinels=(),
            assigned_sentinels=(),
            direction_confidence_component=1.0,
            anchors_confidence_component=score,
            cycle_confidence_component=1.0,
            confidence_score=score,
            hard_fail=not anchors_unique_valid,
            remediation_action="No action needed." if anchors_unique_valid else "Assign valid corner anchors before saving calibration.",
            remediation_hints=hints,
        )

    def auto_detection_status(self) -> str:
        if int(self.detected_device_zone_count) > 0 and int(self.device_zone_count) == int(self.detected_device_zone_count):
            return f"Using auto-detected strip zone count {self.device_zone_count}."
        return f"Using configured strip zone count {self.device_zone_count}."

    def effective_device_zone_count(self) -> int:
        return max(1, int(self.device_zone_count))

    def resolved_mapping_snapshot(self) -> CalibrationMappingSnapshot:
        return resolve_calibration_mapping(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            manual_mapping_enabled=False,
            explicit_zone_map=None,
            corner_zone_offsets=None,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model="corner_anchored",
        )

    def mapping_preview_text(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        return (
            f"{self.auto_detection_status()}\n"
            f"Anchors TL/TR/BR/BL: {self.corner_anchor_top_left}/{self.corner_anchor_top_right}/{self.corner_anchor_bottom_right}/{self.corner_anchor_bottom_left}\n"
            "Simple corner calibration preview\n"
            f"{mapping_preview_text(zone_count=self.zone_count, device_zone_count=self.effective_device_zone_count(), zone_offset=self.zone_offset, reverse_zones=self.reverse_zones, explicit_zone_map=None, corner_zone_offsets=None, corner_anchor_top_left=self.corner_anchor_top_left, corner_anchor_top_right=self.corner_anchor_top_right, corner_anchor_bottom_right=self.corner_anchor_bottom_right, corner_anchor_bottom_left=self.corner_anchor_bottom_left, calibration_model='corner_anchored', resolved_mapping=snapshot)}"
        )

    def mapping_preview_visual(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        return mapping_preview_visual(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=None,
            corner_zone_offsets=None,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model="corner_anchored",
            resolved_mapping=snapshot,
        )

    def _corner_steps(self, resolved_mapping: CalibrationMappingSnapshot | None = None) -> list[CalibrationStep]:
        snapshot = resolved_mapping or self.resolved_mapping_snapshot()
        return corner_anchor_steps(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=None,
            corner_zone_offsets=None,
            start_anchor=None,
            calibration_model="corner_anchored",
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            resolved_mapping=snapshot.device_to_source_indices,
        )

    def step_for_mode(self, mode: str, step: int) -> CalibrationStep:
        snapshot = self.resolved_mapping_snapshot()
        if mode == "corner+offset alignment":
            anchors = self._corner_steps(snapshot)
            anchor = anchors[step % len(anchors)]
            return CalibrationStep(
                device_zone_index=anchor.device_zone_index,
                source_zone_index=anchor.source_zone_index,
                label=(
                    f"Corner assignment | zone offset={self.zone_offset:+d} | test zone step {step % len(anchors) + 1}/{len(anchors)} "
                    f"| reverse={'on' if self.reverse_zones else 'off'} | {anchor.label}"
                ),
            )
        if mode == "coverage sanity":
            return coverage_sanity_step(
                step=step,
                zone_count=self.zone_count,
                device_zone_count=self.effective_device_zone_count(),
                zone_offset=self.zone_offset,
                reverse_zones=self.reverse_zones,
                explicit_zone_map=None,
                corner_zone_offsets=None,
                calibration_model="corner_anchored",
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
            explicit_zone_map=None,
            corner_zone_offsets=None,
            calibration_model="corner_anchored",
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
        self.current_test_step = int(step)
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
