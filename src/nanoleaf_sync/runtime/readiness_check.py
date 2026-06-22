from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nanoleaf_sync.capture.backend_selection import normalize_backend_preference
from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.presets import (
    COLOR_STYLE_PRESETS,
    DISPLAY_PRESETS,
    EDGE_LOCALITY_PRESETS,
    LAYOUT_PRESETS,
    MOTION_PRESETS,
    SAMPLING_QUALITY_PRESETS,
)
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.runtime.calibration_resolver import (
    evaluate_device_zone_authority,
    resolve_calibration_mapping,
)
from nanoleaf_sync.runtime.zone_derivation import source_side_counts_from_config
from nanoleaf_sync.service import _resolve_capture_dims

READY_STATUS = "Ready"
NEEDS_CALIBRATION_STATUS = "Needs calibration"
DEVICE_PROBLEM_STATUS = "Device problem"
CAPTURE_PROBLEM_STATUS = "Capture problem"
CONFIG_PROBLEM_STATUS = "Config problem"


@dataclass(frozen=True)
class ReadinessIssue:
    check: str
    reason: str
    fix: str
    category: str


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    issues: tuple[ReadinessIssue, ...]

    @property
    def ready(self) -> bool:
        return self.status == READY_STATUS and not self.issues


def _probe_capture_backend(config: AppConfig) -> str | None:
    width, height = _resolve_capture_dims(config)
    backend = create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=bool(getattr(config, "use_mock_capture", False)),
        prefer_backend=str(getattr(config, "prefer_backend", "auto")),
        hdr_max_nits=float(getattr(config, "hdr_max_nits", 1000.0)),
        hdr_transfer=str(getattr(config, "hdr_transfer", "srgb")),
        hdr_primaries=str(getattr(config, "hdr_primaries", "bt709")),
        auto_probe_enabled=bool(getattr(config, "auto_probe_enabled", True)),
        cached_probe_winner=str(getattr(config, "auto_selected_backend", "") or None),
    )
    close_fn = getattr(backend, "close", None)
    if callable(close_fn):
        close_fn()
    return None


def _probe_device(config: AppConfig) -> str | None:
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(vid=int(config.device_vid), pid=int(config.device_pid)),
        output_channel_order=str(getattr(config, "output_channel_order", "grb")),
        configured_zone_count=int(getattr(config, "device_zone_count", 0) or 0),
    )
    try:
        driver.initialize()
    finally:
        driver.close()
    return None


def run_readiness_check(
    *,
    config: AppConfig,
    runtime_status: dict | None = None,
    source_zone_count: int | None = None,
    capture_probe: Callable[[AppConfig], str | None] | None = None,
    device_probe: Callable[[AppConfig], str | None] | None = None,
) -> ReadinessReport:
    status = runtime_status or {}
    issues: list[ReadinessIssue] = []

    try:
        normalized = validate_config(config)
    except Exception as exc:
        return ReadinessReport(
            status=CONFIG_PROBLEM_STATUS,
            issues=(
                ReadinessIssue(
                    check="config-load",
                    reason=f"Config could not be validated: {exc}",
                    fix="Open Settings and Save to repair config values",
                    category=CONFIG_PROBLEM_STATUS,
                ),
            ),
        )

    effective_source_count = int(source_zone_count or len(normalized.zones) or 0)
    manual_strip_count = int(getattr(normalized, "device_zone_count", 0) or 0)
    if manual_strip_count <= 0:
        issues.append(
            ReadinessIssue(
                check="strip-count",
                reason="Manual strip LED zone count is not set.",
                fix="Set strip LED zone count",
                category=CONFIG_PROBLEM_STATUS,
            )
        )
    if manual_strip_count > 0 and effective_source_count != manual_strip_count:
        issues.append(
            ReadinessIssue(
                check="source-zone-count",
                reason=(
                    "Source zone count does not match strip LED zone count "
                    f"({effective_source_count} != {manual_strip_count})."
                ),
                fix="Match source zone count to strip LED zone count",
                category=NEEDS_CALIBRATION_STATUS,
            )
        )

    detected_from_status = status.get("detected_device_zone_count")
    if detected_from_status is None:
        detected_from_status = status.get("device_zone_count")
    zone_authority = evaluate_device_zone_authority(
        config=normalized,
        detected_device_zone_count=detected_from_status,
    )
    if zone_authority.blocked:
        issues.append(
            ReadinessIssue(
                check="device-zone-count",
                reason=(
                    "USB strip zone count does not match calibration/config "
                    f"(detected={zone_authority.detected_device_zone_count}, "
                    f"configured={zone_authority.configured_device_zone_count})."
                ),
                fix="Rerun calibration or enable allow_zone_count_override",
                category=DEVICE_PROBLEM_STATUS,
            )
        )

    calibration = normalized.effective_calibration()
    anchors: dict[str, int | None] = {
        "top_left": int(getattr(calibration, "corner_anchor_top_left", -1)),
        "top_right": int(getattr(calibration, "corner_anchor_top_right", -1)),
        "bottom_right": int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        "bottom_left": int(getattr(calibration, "corner_anchor_bottom_left", -1)),
    }
    anchor_validation = validate_corner_anchors(
        anchors=anchors,
        device_zone_count=max(1, manual_strip_count),  # type: ignore[arg-type]
    )
    if not anchor_validation.valid:
        issues.append(
            ReadinessIssue(
                check="anchors",
                reason="Corner anchors are missing, duplicated, or out of range.",
                fix="Assign all four corners",
                category=NEEDS_CALIBRATION_STATUS,
            )
        )

    mapping = resolve_calibration_mapping(
        zone_count=max(1, effective_source_count),
        device_zone_count=max(1, manual_strip_count),
        reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
        corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
        corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
        corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        calibration_model="corner_anchored",
        source_side_counts=source_side_counts_from_config(normalized),
    )
    if mapping.validation_warnings or len(mapping.device_to_source_indices) != max(
        1, manual_strip_count
    ):
        issues.append(
            ReadinessIssue(
                check="calibration-mapping",
                reason="Calibration mapping could not be resolved cleanly.",
                fix="Run calibration again",
                category=NEEDS_CALIBRATION_STATUS,
            )
        )

    if str(getattr(normalized, "layout_preset", "")) not in LAYOUT_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-layout",
                "Layout preset is invalid.",
                "Pick a valid layout preset",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "edge_locality", "")) not in EDGE_LOCALITY_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-edge-locality",
                "Edge locality preset is invalid.",
                "Pick a valid edge locality",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "sampling_quality", "")) not in SAMPLING_QUALITY_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-quality",
                "Sampling quality preset is invalid.",
                "Pick a valid quality preset",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "motion_preset", "")) not in MOTION_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-motion",
                "Motion preset is invalid.",
                "Pick a valid motion preset",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "color_style", "")) not in COLOR_STYLE_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-color-style",
                "Color style preset is invalid.",
                "Pick a valid color style",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "display_preset", "")) not in DISPLAY_PRESETS:
        issues.append(
            ReadinessIssue(
                "preset-display",
                "Display preset is invalid.",
                "Pick SDR, HDR, or Auto",
                CONFIG_PROBLEM_STATUS,
            )
        )

    if str(getattr(normalized, "hdr_transfer", "")) not in {"srgb", "pq"}:
        issues.append(
            ReadinessIssue(
                "hdr-transfer",
                "HDR transfer setting is invalid.",
                "Set HDR transfer to sRGB or PQ",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if str(getattr(normalized, "hdr_primaries", "")) not in {"bt709", "bt2020"}:
        issues.append(
            ReadinessIssue(
                "hdr-primaries",
                "HDR primaries setting is invalid.",
                "Set HDR primaries to BT.709 or BT.2020",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if not (80.0 <= float(getattr(normalized, "hdr_max_nits", 0.0)) <= 10000.0):
        issues.append(
            ReadinessIssue(
                "hdr-max-nits",
                "HDR max nits is out of range.",
                "Set HDR max nits between 80 and 10000",
                CONFIG_PROBLEM_STATUS,
            )
        )
    if not (80.0 <= float(getattr(normalized, "sdr_boost_nits", 0.0)) <= 1000.0):
        issues.append(
            ReadinessIssue(
                "sdr-boost-nits",
                "SDR white reference is out of range.",
                "Set SDR white reference between 80 and 1000 nits",
                CONFIG_PROBLEM_STATUS,
            )
        )

    if (
        bool(getattr(normalized, "wizard_completed", False))
        and str(getattr(normalized, "wizard_in_progress_state", "")).strip()
    ):
        issues.append(
            ReadinessIssue(
                check="wizard-draft",
                reason="A stale wizard draft is still present after setup completion.",
                fix="Reset wizard draft by completing Set up strip… again",
                category=CONFIG_PROBLEM_STATUS,
            )
        )

    if bool(status.get("running")) and int(status.get("consecutive_errors") or 0) >= int(
        status.get("max_consecutive_errors") or 1
    ):
        issues.append(
            ReadinessIssue(
                check="runtime-loop",
                reason="Runtime loop appears stuck in repeated error recovery.",
                fix="Stop and start mirroring from the tray menu",
                category=CONFIG_PROBLEM_STATUS,
            )
        )

    capture_runner = capture_probe or _probe_capture_backend
    try:
        capture_error = capture_runner(normalized)
        if capture_error:
            raise RuntimeError(capture_error)
    except Exception as exc:
        issues.append(
            ReadinessIssue(
                check="capture-backend",
                reason=(
                    f"Capture backend "
                    f"'{normalize_backend_preference(normalized.prefer_backend)}' "
                    f"failed to initialize: {exc}"
                ),
                fix="Select another capture backend",
                category=CAPTURE_PROBLEM_STATUS,
            )
        )

    device_runner = device_probe or _probe_device
    try:
        device_error = device_runner(normalized)
        if device_error:
            raise RuntimeError(device_error)
    except Exception as exc:
        lowered = str(exc).lower()
        fix = "Reconnect the Nanoleaf strip"
        if "permission" in lowered or "access" in lowered or "udev" in lowered:
            fix = "Run udev setup"
        issues.append(
            ReadinessIssue(
                check="hid-device",
                reason=f"Nanoleaf HID device could not be opened: {exc}",
                fix=fix,
                category=DEVICE_PROBLEM_STATUS,
            )
        )

    if not issues:
        return ReadinessReport(status=READY_STATUS, issues=())
    if any(issue.category == DEVICE_PROBLEM_STATUS for issue in issues):
        return ReadinessReport(status=DEVICE_PROBLEM_STATUS, issues=tuple(issues))
    if any(issue.category == CAPTURE_PROBLEM_STATUS for issue in issues):
        return ReadinessReport(status=CAPTURE_PROBLEM_STATUS, issues=tuple(issues))
    if any(issue.category == NEEDS_CALIBRATION_STATUS for issue in issues):
        return ReadinessReport(status=NEEDS_CALIBRATION_STATUS, issues=tuple(issues))
    return ReadinessReport(status=CONFIG_PROBLEM_STATUS, issues=tuple(issues))
