from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.runtime.calibration_resolver import (
    CalibrationMappingSnapshot,
    evaluate_device_zone_authority,
    resolve_calibration_mapping,
)
from nanoleaf_sync.ui.calibration_preview import (
    CalibrationStep,
    calibration_test_frame,
    corner_anchor_steps,
    coverage_sanity_step,
    single_zone_step,
)
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text, mapping_preview_visual

logger = logging.getLogger(__name__)

DEFAULT_DERIVED_ZONE_COUNT = 8


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
            f"cycle={'ok' if self.cycle_replay_confirmed else 'fix'})"
        )


@dataclass
class CalibrationState:
    # Active/simple state
    zone_count: int
    layout_preset: str
    reverse_zones: bool
    device_zone_count: int
    current_test_step: int = 0
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1
    detected_device_zone_count: int = 0
    source_zones_user_configured: bool = False
    source_side_counts: list[int] = field(default_factory=list)

    device_zone_count_source: str = ""
    device_zone_override_active: bool = False

    calibration_model: str = "corner_anchored"

    @classmethod
    def from_config(cls, cfg: AppConfig, runtime_status: dict | None = None) -> CalibrationState:
        runtime_status = runtime_status or {}
        calibration = cfg.effective_calibration()
        layout_preset = str(getattr(cfg, "layout_preset", "edge_strip"))
        source_zone_count = len(cfg.zones) if cfg.zones else 0
        source_zones_user_configured = bool(cfg.zones)
        detected = int(runtime_status.get("detected_device_zone_count") or 0)
        if detected <= 0:
            detected = int(runtime_status.get("device_zone_count") or 0)
        zone_authority = evaluate_device_zone_authority(
            config=cfg,
            detected_device_zone_count=detected if detected > 0 else None,
        )
        effective_device_zone_count = int(zone_authority.effective_device_zone_count)
        configured_device_zone_count = int(zone_authority.configured_device_zone_count)
        if layout_preset == "edge_strip" and effective_device_zone_count > 0:
            source_zone_count = effective_device_zone_count
            source_zones_user_configured = False
        if source_zone_count <= 0:
            if effective_device_zone_count > 0:
                source_zone_count = effective_device_zone_count
            else:
                source_zone_count = DEFAULT_DERIVED_ZONE_COUNT
        if configured_device_zone_count <= 0:
            configured_device_zone_count = max(1, int(source_zone_count))

        return cls(
            zone_count=max(1, int(source_zone_count)),
            layout_preset=layout_preset,
            reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
            device_zone_count=max(1, int(effective_device_zone_count)),
            corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
            corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
            corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
            corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
            detected_device_zone_count=detected if detected > 0 else 0,
            source_zones_user_configured=source_zones_user_configured,
            source_side_counts=[
                int(v) for v in (getattr(cfg, "source_side_counts", None) or [])[:4]
            ],
            device_zone_count_source=str(zone_authority.device_zone_count_source or ""),
            device_zone_override_active=bool(zone_authority.override_active),
            calibration_model="corner_anchored",
        )

    def validation_report(self) -> CalibrationVerificationReport:
        anchors = {
            "top_left": self.corner_anchor_top_left if self.corner_anchor_top_left >= 0 else None,
            "top_right": self.corner_anchor_top_right
            if self.corner_anchor_top_right >= 0
            else None,
            "bottom_right": self.corner_anchor_bottom_right
            if self.corner_anchor_bottom_right >= 0
            else None,
            "bottom_left": self.corner_anchor_bottom_left
            if self.corner_anchor_bottom_left >= 0
            else None,
        }
        anchor_validation = validate_corner_anchors(
            anchors=anchors, device_zone_count=self.effective_device_zone_count()
        )
        anchors_unique_valid = bool(anchor_validation.valid)
        score = 1.0 if anchors_unique_valid else 0.0
        hints = (
            ()
            if anchors_unique_valid
            else ("Assign four unique in-range corner anchors (TL/TR/BR/BL).",)
        )
        return CalibrationVerificationReport(
            outcome_status="pass" if anchors_unique_valid else "fail",
            direction_confirmed=True,
            anchors_unique_valid=anchors_unique_valid,
            cycle_replay_confirmed=True,
            direction_confidence_component=1.0,
            anchors_confidence_component=score,
            cycle_confidence_component=1.0,
            confidence_score=score,
            hard_fail=not anchors_unique_valid,
            remediation_action="No action needed."
            if anchors_unique_valid
            else "Assign valid corner anchors before saving calibration.",
            remediation_hints=hints,
        )

    def auto_detection_status(self) -> str:
        if self.device_zone_override_active:
            return (
                f"Using manual strip zone count {self.device_zone_count} "
                f"(override active; source={self.device_zone_count_source or 'configured'})."
            )
        if self.device_zone_count_source == "detected-usb":
            return f"Using USB-reported strip zone count {self.device_zone_count}."
        return (
            f"Using manual strip zone count {self.device_zone_count}."
            if int(self.device_zone_count) > 0
            else "Manual strip zone count is required."
        )

    def effective_device_zone_count(self) -> int:
        return max(1, int(self.device_zone_count))

    def resolved_mapping_snapshot(self) -> CalibrationMappingSnapshot:
        raw_counts = list(self.source_side_counts or [])
        side_counts: tuple[int, int, int, int] | None = None
        if len(raw_counts) == 4 and sum(int(v) for v in raw_counts) > 0:
            side_counts = tuple(int(v) for v in raw_counts)
        return resolve_calibration_mapping(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            reverse_zones=self.reverse_zones,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model="corner_anchored",
            source_side_counts=side_counts,
        )

    def mapping_preview_text(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        source_mode = "user-configured" if self.source_zones_user_configured else "auto-derived"
        preview_text = mapping_preview_text(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            reverse_zones=self.reverse_zones,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model="corner_anchored",
            resolved_mapping=snapshot,
        )
        return (
            f"{self.auto_detection_status()}\n"
            f"Layout preset: {self.layout_preset} | source zones: {self.zone_count} | "
            f"strip zones: {self.effective_device_zone_count()} | source mode: {source_mode}\n"
            f"Anchors TL/TR/BR/BL: {self.corner_anchor_top_left}/"
            f"{self.corner_anchor_top_right}/{self.corner_anchor_bottom_right}/"
            f"{self.corner_anchor_bottom_left}\n"
            "Simple corner calibration preview\n"
            f"{preview_text}"
        )

    def mapping_preview_visual(self) -> str:
        snapshot = self.resolved_mapping_snapshot()
        return mapping_preview_visual(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            reverse_zones=self.reverse_zones,
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            calibration_model="corner_anchored",
            resolved_mapping=snapshot,
        )

    def _corner_steps(
        self, resolved_mapping: CalibrationMappingSnapshot | None = None
    ) -> list[CalibrationStep]:
        snapshot = resolved_mapping or self.resolved_mapping_snapshot()
        return corner_anchor_steps(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            reverse_zones=self.reverse_zones,
            calibration_model="corner_anchored",
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            resolved_mapping=snapshot.device_to_source_indices,
        )

    def step_for_mode(self, mode: str, step: int) -> CalibrationStep:
        if mode == "physical zone walk":
            total = self.effective_device_zone_count()
            device_zone_index = int(step) % total
            return CalibrationStep(
                device_zone_index=device_zone_index,
                source_zone_index=device_zone_index % max(1, int(self.zone_count)),
                label=(
                    f"Physical strip walk | test zone step {device_zone_index + 1}/{total} "
                    f"| raw strip zone {device_zone_index}"
                ),
            )
        snapshot = self.resolved_mapping_snapshot()
        if mode == "corner+offset alignment":
            anchors = self._corner_steps(snapshot)
            anchor = anchors[step % len(anchors)]
            return CalibrationStep(
                device_zone_index=anchor.device_zone_index,
                source_zone_index=anchor.source_zone_index,
                label=(
                    f"Corner assignment | test zone step {step % len(anchors) + 1}/{len(anchors)} "
                    f"| reverse={'on' if self.reverse_zones else 'off'} | {anchor.label}"
                ),
            )
        if mode == "coverage sanity":
            return coverage_sanity_step(
                step=step,
                zone_count=self.zone_count,
                device_zone_count=self.effective_device_zone_count(),
                reverse_zones=self.reverse_zones,
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
            reverse_zones=self.reverse_zones,
            calibration_model="corner_anchored",
            corner_anchor_top_left=self.corner_anchor_top_left,
            corner_anchor_top_right=self.corner_anchor_top_right,
            corner_anchor_bottom_right=self.corner_anchor_bottom_right,
            corner_anchor_bottom_left=self.corner_anchor_bottom_left,
            resolved_mapping=snapshot.device_to_source_indices,
            label_prefix=prefix,
        )

    def cycle_length(self, mode: str) -> int:
        if mode == "physical zone walk":
            return max(1, self.effective_device_zone_count())
        if mode == "corner+offset alignment":
            return max(1, len(self._corner_steps()))
        return max(1, self.effective_device_zone_count())

    def frame_for_step(
        self, *, mode: str, step: int, brightness: float, all_off_except_active: bool
    ) -> list[tuple[int, int, int]]:
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
    effective = str(
        status.get("effective_capture_backend") or status.get("capture_backend") or ""
    ).strip()
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


def build_testing_panel_state(
    *, state: CalibrationState, runtime_status: dict | None, cfg: AppConfig, mode: str, step: int
) -> TestingPanelState:
    backend = backend_selection_info(runtime_status, cfg)
    active = state.step_for_mode(mode, step)
    return TestingPanelState(
        backend_summary=(
            f"Requested backend policy: {backend.requested_policy} | "
            f"Selected backend: {backend.selected_backend} | "
            f"Effective runtime backend: {backend.effective_backend} | "
            f"Source: {backend.source} | Reason: {backend.reason}"
            + (f" | Unresolved: {backend.unresolved_reason}" if backend.unresolved_reason else "")
        ),
        zone_mode_summary=("Strip LED zone mode: configured")
        + f" | {state.auto_detection_status()}",
        effective_zone_count=state.effective_device_zone_count(),
        active_test_description=active.label,
    )


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
        recorded_at_utc=datetime.now(UTC).isoformat(),
        details=str(details),
    )


def should_auto_run_latency_probe(
    *, policy: str, last_result: LatencyProbeResult | None, active_backend: str
) -> bool:
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
        return "Live latency: Not measured | Start mirroring to collect live latency samples."
    if result.measurement_kind == "measured":
        return (
            f"Live latency: {result.measured_latency_ms:.1f} ms | "
            f"backend={result.selected_backend} | source={result.selection_source} | "
            f"trigger={result.triggered_by} | confidence={result.confidence_note}"
            + (f" | {result.details}" if result.details else "")
        )
    if result.measurement_kind == "unavailable":
        return f"Live latency: Not measured | {result.confidence_note}" + (
            f" | {result.details}" if result.details else ""
        )
    return (
        f"Live latency: Not measured | Unsupported latency result kind '{result.measurement_kind}'."
    )
