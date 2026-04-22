from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ZoneConfig:
    """
    Zone rectangles expressed in normalized screen coordinates.

    Values are floats in [0, 1]:
    - x, y: top-left corner
    - w, h: width/height
    """

    x: float
    y: float
    w: float
    h: float


@dataclass
class CalibrationConfig:
    # Versioned schema for calibration payload migrations.
    schema_version: int = 1
    # Canonical version marker used by schema migrations.
    calibration_schema_version: int = 1
    # Authoritative calibration model for resolving mapping.
    calibration_model: str = "offset_direction"
    # Canonical normalization of calibration modes:
    # - offset_direction: use `normalized_zone_offset` + `normalized_reverse_zones`
    # - corner_anchored: use `normalized_corner_anchors`
    # - manual_explicit_map: use `normalized_manual_zone_map`
    device_zone_count: int = 0
    output_channel_order: str = "grb"
    normalized_zone_offset: int = 0
    normalized_reverse_zones: bool = False
    normalized_corner_anchors: list[int] = field(default_factory=list)
    normalized_manual_zone_map: list[int] = field(default_factory=list)
    zone_offset: int = 0
    reverse_zones: bool = False
    manual_mapping_enabled: bool = False
    explicit_zone_map: list[int] = field(default_factory=list)
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1
    corner_start_anchor: int = -1
    corner_offsets_enabled: bool = False
    corner_zone_offsets: list[int] = field(default_factory=list)


@dataclass
class AppConfig:
    # Capture
    fps: int = 30
    # Auto chooses backend based on platform capabilities.
    # On CachyOS, auto currently prefers kmsgrab for lower latency.
    prefer_backend: str = "auto"

    # Color -> device mapping
    brightness: float = 1.0  # [0.0, 1.0]
    smoothing: float = 0.5  # One-Euro minimum responsiveness in [0.0, 1.0]
    smoothing_speed: float = 0.75  # Adaptive motion gain in [0.0, 4.0]; lower = slower response / more smoothing.
    led_gamma: float = 1.0  # Output correction for LED electrical response.

    # Zones
    zones: list[ZoneConfig] = field(default_factory=list)
    # If zones is empty, runtime derives zones from strip zone count + preset.
    # With the "horizontal" preset and count=1, this becomes a full-screen zone.
    # With the "edge-weighted" preset, make_edge_weighted_zones keeps edge strips.
    # Zone sampling stride (1 = every pixel, 2 = every other pixel, etc.).
    # Larger values reduce CPU cost at the expense of color precision.
    zone_sampling_stride: int = 1
    # User-facing quality preset for screen sampling.
    # Low = best performance, Balanced = default, High = best visual fidelity.
    sampling_quality: str = "balanced"
    # High-count target for edge preset capture thickness in normalized units.
    # Lower zone counts are automatically thinner to avoid center-heavy sampling.
    edge_sampling_thickness: float = 0.12
    zone_preset: str = "edge-weighted"
    color_mode: str = "default"
    # Tracks whether the first-run display configurator has been completed.
    wizard_completed: bool = False
    # Serialized in-progress setup wizard state for resume/recovery.
    # Stored as JSON payload; empty string means no active draft.
    wizard_in_progress_state: str = ""
    # Wizard choice: False=SDR path, True=HDR path.
    hdr_enabled: bool = False
    start_on_launch: bool = False

    # KDE compositor HDR controls for SDR content on HDR displays.
    compositor_hdr_mode: bool = False
    # Plasma SDR white reference in nits (80 = no compositor SDR boost).
    sdr_boost_nits: float = 80.0

    # USB / device
    device_vid: int = 0x37FA
    device_pid: int = 0x8202

    # Capture backend toggle.
    # Default to real capture (kwin-dbus) for KDE Plasma; set True for diagnostics mode.
    use_mock_capture: bool = False
    # Probe auto backend candidates at runtime; can still be overridden by env kill switch.
    auto_probe_enabled: bool = True
    # Auto-probe cache invalidation policy.
    # - first-run: probe only if there is no cached winner.
    # - each-boot: probe once per process start.
    # - on-change: probe when environment signature changes.
    auto_probe_policy: str = "on-change"
    # Persisted winner from previous auto-probe runs.
    auto_selected_backend: str = ""
    # Persisted environment signature from previous auto-probe run.
    auto_probe_signature: str = ""
    # Last successful auto-probe timestamp in UTC ISO-8601 format.
    auto_probe_timestamp: str = ""

    # HDR conversion controls (used by HDR-capable capture paths / metadata-aware conversion).
    hdr_max_nits: float = 1000.0
    hdr_transfer: str = "srgb"
    hdr_primaries: str = "bt709"

    # Device zone calibration (mapping sampled screen zones to physical strip zones)
    calibration_schema_version: int = 1
    # Canonical, migration-safe calibration payload.
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    # Persisted config should always carry a concrete value.
    # Legacy configs with 0 are migrated during normalization.
    device_zone_count: int = 0
    # Physical channel order expected by the LED strip controller.
    # Defaults to GRB for currently supported Nanoleaf USB strip hardware.
    output_channel_order: str = "grb"
    zone_offset: int = 0
    reverse_zones: bool = False
    # Explicitly controls whether `explicit_zone_map` is active.
    manual_mapping_enabled: bool = False
    # Authoritative calibration model for resolving mapping.
    # - offset_direction: legacy global offset + reverse toggle.
    # - corner_anchored: derive explicit map from four corner anchors.
    # - manual_explicit_map: force explicit map semantics.
    calibration_model: str = "offset_direction"
    # Optional explicit mapping: list of screen-zone indices for each device zone.
    # Applied only when `manual_mapping_enabled` is True.
    explicit_zone_map: list[int] = field(default_factory=list)

    # Canonical calibration anchors (physical strip zones at monitor corners).
    # Negative value means unassigned.
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1

    # Guided corner calibration: optional explicit top-left device anchor index.
    # Negative means inferred from current mapping.
    corner_start_anchor: int = -1
    # Optional advanced per-corner correction over the base mapping.
    # Order: [top-left, top-right, bottom-right, bottom-left].
    # Values are source-zone index offsets blended across each edge.
    corner_offsets_enabled: bool = False
    corner_zone_offsets: list[int] = field(default_factory=list)

    # Latency diagnostics/checker policy and latest visible result.
    auto_latency_policy: str = "manual"
    latency_last_backend: str = ""
    latency_last_value_ms: float = 0.0
    latency_last_trigger: str = ""
    latency_last_timestamp: str = ""
    calibration_validation_confidence: float = 0.0
    calibration_validation_summary: str = ""

    # Recovery policy
    max_consecutive_errors: int = 5
    reinit_backoff_ms: int = 500

    # Logging / misc
    status_log_interval_s: float = 5.0
    verbose: bool = False

    def effective_calibration(self) -> CalibrationConfig:
        """
        Return a canonical calibration snapshot for runtime/UI consumers.

        The nested ``calibration`` payload is authoritative. Top-level fields are
        retained for backward compatibility and mirrored by normalization.
        """
        calibration = self.calibration or CalibrationConfig()
        defaults = CalibrationConfig()
        has_explicit_block = calibration != CalibrationConfig()

        def calibration_or_legacy(field: str, default):
            calibration_value = getattr(calibration, field, default)
            legacy_value = getattr(self, field, default)
            if has_explicit_block:
                return calibration_value
            if calibration_value == default and legacy_value != default:
                return legacy_value
            return calibration_value

        return CalibrationConfig(
            schema_version=int(
                getattr(self, "calibration_schema_version", getattr(calibration, "schema_version", 1)) or 1
            ),
            calibration_schema_version=int(
                getattr(self, "calibration_schema_version", getattr(calibration, "calibration_schema_version", 1))
                or 1
            ),
            calibration_model=str(calibration_or_legacy("calibration_model", defaults.calibration_model)),
            device_zone_count=int(calibration_or_legacy("device_zone_count", defaults.device_zone_count)),
            output_channel_order=str(calibration_or_legacy("output_channel_order", defaults.output_channel_order)),
            normalized_zone_offset=int(
                calibration_or_legacy("normalized_zone_offset", defaults.normalized_zone_offset)
            ),
            normalized_reverse_zones=bool(
                calibration_or_legacy("normalized_reverse_zones", defaults.normalized_reverse_zones)
            ),
            normalized_corner_anchors=[
                int(i)
                for i in (
                    calibration_or_legacy("normalized_corner_anchors", defaults.normalized_corner_anchors) or []
                )
            ],
            normalized_manual_zone_map=[
                int(i)
                for i in (
                    calibration_or_legacy("normalized_manual_zone_map", defaults.normalized_manual_zone_map) or []
                )
            ],
            zone_offset=int(calibration_or_legacy("zone_offset", defaults.zone_offset)),
            reverse_zones=bool(calibration_or_legacy("reverse_zones", defaults.reverse_zones)),
            manual_mapping_enabled=bool(
                calibration_or_legacy("manual_mapping_enabled", defaults.manual_mapping_enabled)
            ),
            explicit_zone_map=[
                int(i)
                for i in (
                    calibration_or_legacy("explicit_zone_map", defaults.explicit_zone_map) or []
                )
            ],
            corner_anchor_top_left=int(
                calibration_or_legacy("corner_anchor_top_left", defaults.corner_anchor_top_left)
            ),
            corner_anchor_top_right=int(
                calibration_or_legacy("corner_anchor_top_right", defaults.corner_anchor_top_right)
            ),
            corner_anchor_bottom_right=int(
                calibration_or_legacy("corner_anchor_bottom_right", defaults.corner_anchor_bottom_right)
            ),
            corner_anchor_bottom_left=int(
                calibration_or_legacy("corner_anchor_bottom_left", defaults.corner_anchor_bottom_left)
            ),
            corner_start_anchor=int(calibration_or_legacy("corner_start_anchor", defaults.corner_start_anchor)),
            corner_offsets_enabled=bool(
                calibration_or_legacy("corner_offsets_enabled", defaults.corner_offsets_enabled)
            ),
            corner_zone_offsets=[
                int(i)
                for i in (
                    calibration_or_legacy("corner_zone_offsets", defaults.corner_zone_offsets) or []
                )
            ],
        )
