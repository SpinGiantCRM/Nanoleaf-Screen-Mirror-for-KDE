from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

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


@dataclass
class LatencyProbeResult:
    backend: str
    measured_latency_ms: float
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

    @classmethod
    def from_config(cls, cfg: AppConfig, runtime_status: dict | None = None) -> "CalibrationState":
        runtime_status = runtime_status or {}
        zone_count = len(cfg.zones) if cfg.zones else (int(getattr(cfg, "device_zone_count", 0)) or 8)
        detected = int(runtime_status.get("device_zone_count") or 0)
        return cls(
            zone_count=max(1, int(zone_count)),
            zone_preset=str(getattr(cfg, "zone_preset", "edge-weighted")),
            reverse_zones=bool(getattr(cfg, "reverse_zones", False)),
            zone_offset=int(getattr(cfg, "zone_offset", 0)),
            device_zone_count=max(1, int(getattr(cfg, "device_zone_count", 0)) or max(1, int(zone_count))),
            auto_device_zone_count=int(getattr(cfg, "device_zone_count", 0)) == 0,
            detected_device_zone_count=max(0, detected),
            explicit_zone_map=[int(i) for i in (getattr(cfg, "explicit_zone_map", []) or [])],
            manual_mapping_enabled=bool(getattr(cfg, "explicit_zone_map", [])),
            corner_start_anchor=int(getattr(cfg, "corner_start_anchor", -1)),
        )

    def effective_device_zone_count(self) -> int:
        if self.auto_device_zone_count:
            return self.detected_device_zone_count if self.detected_device_zone_count > 0 else self.zone_count
        return self.device_zone_count

    def mapping_preview_text(self) -> str:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        detection = (
            f"Device zone count: auto (detected {self.detected_device_zone_count})"
            if self.auto_device_zone_count and self.detected_device_zone_count > 0
            else (
                "Device zone count: auto (using source zone count)"
                if self.auto_device_zone_count
                else f"Device zone count: manual {self.device_zone_count}"
            )
        )
        return (
            f"{detection}\n"
            f"Offset currently applied: {self.zone_offset:+d}\n"
            f"{'Manual mapping enabled' if self.manual_mapping_enabled else 'Corner anchors inferred from current mapping'}\n"
            f"{mapping_preview_text(zone_count=self.zone_count, device_zone_count=self.effective_device_zone_count(), zone_offset=self.zone_offset, reverse_zones=self.reverse_zones, explicit_zone_map=explicit)}"
        )

    def mapping_preview_visual(self) -> str:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        return mapping_preview_visual(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
        )

    def _corner_steps(self) -> list[CalibrationStep]:
        explicit = self.explicit_zone_map if self.manual_mapping_enabled else []
        anchors = corner_anchor_steps(
            zone_count=self.zone_count,
            device_zone_count=self.effective_device_zone_count(),
            zone_offset=self.zone_offset,
            reverse_zones=self.reverse_zones,
            explicit_zone_map=explicit,
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


def next_corner_start_anchor(current: int, *, device_zone_count: int) -> int:
    total = max(1, int(device_zone_count))
    return (int(current) + 1) % total


def build_latency_result(*, backend: str, measured_latency_ms: float, triggered_by: str, details: str = "") -> LatencyProbeResult:
    return LatencyProbeResult(
        backend=str(backend),
        measured_latency_ms=float(measured_latency_ms),
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
        return str(last_result.backend) != str(active_backend)
    return False


def latency_result_summary(result: LatencyProbeResult | None) -> str:
    if result is None:
        return "Latency checker has not been run yet."
    return (
        f"Latest latency check: {result.measured_latency_ms:.1f} ms | backend={result.backend} | "
        f"trigger={result.triggered_by} | at={result.recorded_at_utc}"
        + (f" | {result.details}" if result.details else "")
    )
