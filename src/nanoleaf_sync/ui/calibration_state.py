from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from nanoleaf_sync.config.model import AppConfig
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
class CalibrationState:
    zone_count: int
    zone_preset: str
    reverse_zones: bool
    zone_offset: int
    device_zone_count: int
    auto_device_zone_count: bool
    detected_device_zone_count: int
    explicit_zone_map: list[int] = field(default_factory=list)
    manual_mapping_enabled: bool = False
    corner_start_anchor: int = -1
    corner_offsets_enabled: bool = False
    corner_zone_offsets: list[int] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: AppConfig, runtime_status: dict | None = None) -> "CalibrationState":
        runtime_status = runtime_status or {}
        configured_zone_count = len(cfg.zones) if cfg.zones else 0
        if configured_zone_count <= 0:
            configured_zone_count = int(getattr(cfg, "device_zone_count", 0))
        if configured_zone_count <= 0:
            configured_zone_count = 8

        detected = int(runtime_status.get("device_zone_count") or 0)
        return cls(
            zone_count=max(1, int(configured_zone_count)),
            zone_preset=str(getattr(cfg, "zone_preset", "edge-weighted")),
            reverse_zones=bool(getattr(cfg, "reverse_zones", False)),
            zone_offset=int(getattr(cfg, "zone_offset", 0)),
            device_zone_count=max(1, int(getattr(cfg, "device_zone_count", 0)) or max(1, int(configured_zone_count))),
            auto_device_zone_count=int(getattr(cfg, "device_zone_count", 0)) == 0,
            detected_device_zone_count=max(0, detected),
            explicit_zone_map=[int(i) for i in (getattr(cfg, "explicit_zone_map", []) or [])],
            manual_mapping_enabled=bool(getattr(cfg, "explicit_zone_map", [])),
            corner_start_anchor=int(getattr(cfg, "corner_start_anchor", -1)),
            corner_offsets_enabled=bool(getattr(cfg, "corner_offsets_enabled", False)),
            corner_zone_offsets=[int(i) for i in (getattr(cfg, "corner_zone_offsets", []) or [])][:4],
        )

    def active_corner_zone_offsets(self) -> list[int]:
        offsets = self.corner_zone_offsets[:4]
        while len(offsets) < 4:
            offsets.append(0)
        offsets = [max(-CORNER_OFFSET_LIMIT, min(CORNER_OFFSET_LIMIT, int(value))) for value in offsets]
        if not self.corner_offsets_enabled:
            return [0, 0, 0, 0]
        return offsets

    def auto_detection_status(self) -> str:
        if not self.auto_device_zone_count:
            return f"Manual mode: using configured strip zone count {self.device_zone_count}."
        if self.detected_device_zone_count > 0:
            return f"Auto detection succeeded: detected strip zone count {self.detected_device_zone_count}."
        return (
            "Auto detection failed: no device-reported strip zone count was available. "
            f"Using fallback source zone count {self.zone_count}."
        )

    def effective_device_zone_count(self) -> int:
        if self.auto_device_zone_count:
            return self.detected_device_zone_count if self.detected_device_zone_count > 0 else self.zone_count
        return max(1, int(self.device_zone_count))

    def mapping_preview_text(self) -> str:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        return (
            f"{self.auto_detection_status()}\n"
            f"Offset currently applied: {self.zone_offset:+d}\n"
            f"Per-corner refinement (TL/TR/BR/BL): {'/'.join(f'{value:+d}' for value in self.active_corner_zone_offsets())}\n"
            f"{'Manual mapping enabled' if self.manual_mapping_enabled else 'Corner anchors inferred from current mapping'}\n"
            f"{mapping_preview_text(zone_count=self.zone_count, device_zone_count=self.effective_device_zone_count(), zone_offset=self.zone_offset, reverse_zones=self.reverse_zones, explicit_zone_map=explicit, corner_zone_offsets=self.active_corner_zone_offsets())}"
        )

    def mapping_preview_visual(self) -> str:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        return mapping_preview_visual(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
        )

    def _corner_steps(self) -> list[CalibrationStep]:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        anchors = corner_anchor_steps(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
            corner_zone_offsets=self.active_corner_zone_offsets(),
            start_anchor=self.corner_start_anchor if self.corner_start_anchor >= 0 else None,
        )
        return anchors

    def step_for_mode(self, mode: str, step: int) -> CalibrationStep:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        if mode == "corner+offset alignment":
            anchors = self._corner_steps()
            anchor = anchors[step % len(anchors)]
            return CalibrationStep(
                device_zone_index=anchor.device_zone_index,
                source_zone_index=anchor.source_zone_index,
                label=(
                    f"Corner+offset alignment | reverse={'on' if self.reverse_zones else 'off'} | offset={self.zone_offset:+d} | {anchor.label}"
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
            "Device zone mode: auto" if state.auto_device_zone_count else "Device zone mode: manual"
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
    summary_kind = (
        "measured"
        if result.measurement_kind == "measured"
        else ("policy recommendation" if result.measurement_kind == "policy" else "estimated")
    )
    return (
        f"Latest latency check: {result.measured_latency_ms:.1f} ms [{summary_kind}] | "
        f"requested_policy={result.requested_policy} | backend={result.selected_backend} | source={result.selection_source} | "
        f"trigger={result.triggered_by} | confidence={result.confidence_note} | at={result.recorded_at_utc}"
        + (f" | {result.details}" if result.details else "")
    )
