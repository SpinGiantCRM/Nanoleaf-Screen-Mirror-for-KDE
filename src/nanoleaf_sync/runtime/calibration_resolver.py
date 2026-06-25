from __future__ import annotations

from dataclasses import dataclass

from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map, validate_corner_anchors

CALIBRATION_INCOMPLETE_STATUS = "calibration_incomplete"
CALIBRATION_READY_STATUS = "ready"
DEVICE_ZONE_MISMATCH_STATUS = "device_zone_mismatch"
DEVICE_ZONE_MISMATCH_MESSAGE = (
    "device_zone_mismatch: USB strip reported a different LED zone count than "
    "calibration/config. Rerun calibration or enable allow_zone_count_override."
)
CALIBRATION_INCOMPLETE_MESSAGE = (
    "calibration_incomplete: Corner calibration is incomplete; "
    "assign all four unique corner anchors before starting screen mirroring."
)


@dataclass(frozen=True)
class CalibrationMappingSnapshot:
    device_to_source_indices: list[int]
    mode: str
    direction: str
    validation_warnings: tuple[str, ...]
    warning_codes: tuple[str, ...]
    calibration_model: str
    strategy: str

    @property
    def calibration_status(self) -> str:
        if self.validation_warnings or not self.device_to_source_indices:
            return CALIBRATION_INCOMPLETE_STATUS
        return CALIBRATION_READY_STATUS

    @property
    def calibration_incomplete(self) -> bool:
        return self.calibration_status == CALIBRATION_INCOMPLETE_STATUS

    @property
    def status_message(self) -> str:
        if not self.calibration_incomplete:
            return "Calibration is complete."
        details = " ".join(str(item) for item in self.validation_warnings if str(item).strip())
        return f"{CALIBRATION_INCOMPLETE_MESSAGE} {details}".strip()

    @property
    def anchor_validation_ok(self) -> bool:
        return not self.validation_warnings

    @property
    def anchor_validation_errors(self) -> tuple[str, ...]:
        # Backwards-compatible alias for older call-sites/tests.
        return self.validation_warnings


@dataclass(frozen=True)
class CalibrationResolverContext:
    source_zone_count: int
    effective_device_zone_count: int
    detected_device_zone_count: int | None = None


@dataclass(frozen=True)
class DeviceZoneAuthorityResult:
    configured_device_zone_count: int
    detected_device_zone_count: int | None
    effective_device_zone_count: int
    device_zone_count_source: str
    device_zone_count_mismatch: bool
    mapping_repair_required: bool
    override_active: bool
    blocked: bool
    status: str
    message: str


def _configured_device_zone_count(config: AppConfig) -> int:
    calibration = config.effective_calibration()
    configured = int(getattr(calibration, "device_zone_count", 0))
    if configured <= 0:
        configured = int(getattr(config, "device_zone_count", 0) or 0)
    return configured


def evaluate_device_zone_authority(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None,
) -> DeviceZoneAuthorityResult:
    configured = _configured_device_zone_count(config)
    detected = (
        int(detected_device_zone_count)
        if detected_device_zone_count is not None and int(detected_device_zone_count) > 0
        else None
    )
    override_active = bool(getattr(config, "allow_zone_count_override", False))
    mismatch = detected is not None and configured > 0 and int(detected) != int(configured)
    if configured > 0:
        effective = int(configured)
        source = "configured-override" if detected is not None and override_active else "configured"
    elif detected is not None:
        effective = int(detected)
        source = "detected-usb"
    else:
        effective = 1
        source = "fallback"
    blocked = bool(mismatch and not override_active)
    status = CALIBRATION_READY_STATUS
    message = ""
    if blocked:
        status = DEVICE_ZONE_MISMATCH_STATUS
        message = f"{DEVICE_ZONE_MISMATCH_MESSAGE} detected={detected} configured={configured}."
    elif mismatch and override_active:
        message = (
            f"device_zone_override_active: using configured={configured} "
            f"instead of detected={detected}."
        )
    return DeviceZoneAuthorityResult(
        configured_device_zone_count=configured,
        detected_device_zone_count=detected,
        effective_device_zone_count=effective,
        device_zone_count_source=source,
        device_zone_count_mismatch=mismatch,
        mapping_repair_required=blocked,
        override_active=override_active and mismatch,
        blocked=blocked,
        status=status,
        message=message,
    )


def _normalize_anchor(value: int | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed >= 0 else None


def resolve_calibration_mapping(
    *,
    zone_count: int,
    device_zone_count: int,
    reverse_zones: bool,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "corner_anchored",
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    normalized_model = str(calibration_model or "corner_anchored").strip().lower()
    if normalized_model not in {"corner_anchored"}:
        normalized_model = "corner_anchored"
    anchors = {
        "top_left": _normalize_anchor(corner_anchor_top_left),
        "top_right": _normalize_anchor(corner_anchor_top_right),
        "bottom_right": _normalize_anchor(corner_anchor_bottom_right),
        "bottom_left": _normalize_anchor(corner_anchor_bottom_left),
    }

    validation_warnings: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    strategy = "corner_anchored"
    direction = "clockwise"

    normalized_device_zone_count = int(device_zone_count)
    if normalized_device_zone_count <= 0:
        normalized_device_zone_count = 1

    anchor_validation = validate_corner_anchors(
        anchors=anchors, device_zone_count=device_zone_count
    )
    if not anchor_validation.valid:
        validation_warnings = tuple(anchor_validation.errors)
        return CalibrationMappingSnapshot(
            device_to_source_indices=[],
            mode=strategy,
            direction=direction,
            validation_warnings=validation_warnings,
            warning_codes=tuple(validation_warnings),
            strategy=strategy,
            calibration_model=normalized_model,
        )
    effective_anchors = anchors

    derive_device_zone_count = max(4, int(device_zone_count))
    anchor_map = derive_anchor_zone_map(
        zone_count=zone_count,
        device_zone_count=derive_device_zone_count,
        anchors=effective_anchors,
        source_side_counts=source_side_counts,
    )
    selected_explicit_map = list(anchor_map.mapping)
    target_count = max(1, int(device_zone_count))
    if len(selected_explicit_map) != target_count:
        source_count = len(selected_explicit_map)
        selected_explicit_map = [
            int(selected_explicit_map[(idx * source_count) // target_count])
            for idx in range(target_count)
        ]
    direction = anchor_map.direction

    mapping = resolve_device_zone_indices(
        max(1, int(zone_count)),
        device_zone_count=normalized_device_zone_count,
        reverse=bool(reverse_zones),
        fixed_mapping=selected_explicit_map,
    )
    return CalibrationMappingSnapshot(
        device_to_source_indices=mapping,
        mode=strategy,
        direction=direction,
        validation_warnings=validation_warnings,
        warning_codes=warning_codes,
        strategy=strategy,
        calibration_model=normalized_model,
    )


def resolve_calibration_mapping_from_config(
    *,
    config: AppConfig,
    source_zone_count: int,
    detected_device_zone_count: int | None = None,
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    authority = evaluate_device_zone_authority(
        config=config,
        detected_device_zone_count=detected_device_zone_count,
    )
    context = CalibrationResolverContext(
        source_zone_count=int(source_zone_count),
        effective_device_zone_count=max(1, int(authority.effective_device_zone_count)),
        detected_device_zone_count=detected_device_zone_count,
    )
    return resolve_calibration_mapping_with_context(
        config=config,
        context=context,
        source_side_counts=source_side_counts,
    )


def resolve_calibration_mapping_with_context(
    *,
    config: AppConfig,
    context: CalibrationResolverContext,
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    calibration = config.effective_calibration()
    device_zone_count = max(1, int(context.effective_device_zone_count))
    return resolve_calibration_mapping(
        zone_count=int(context.source_zone_count),
        device_zone_count=device_zone_count,
        reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
        corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
        corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
        corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        calibration_model="corner_anchored",
        source_side_counts=source_side_counts,
    )
