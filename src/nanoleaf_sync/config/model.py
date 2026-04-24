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
    calibration_model: str = "corner_anchored"
    device_zone_count: int = 0
    output_channel_order: str = "grb"
    normalized_reverse_zones: bool = False
    normalized_corner_anchors: list[int] = field(default_factory=list)
    reverse_zones: bool = False
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1


@dataclass
class AppConfig:
    # Capture
    fps: int = 30
    # Auto chooses backend based on platform capabilities.
    # On CachyOS, auto prefers kmsgrab for lower latency.
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
    # New preset architecture (canonical model).
    layout_preset: str = "edge_strip"
    edge_locality: str = "balanced"
    sampling_quality: str = "high"
    motion_preset: str = "responsive"
    color_style: str = "ambient"
    display_preset: str = "hdr"
    # Tracks whether the first-run display configurator has been completed.
    wizard_completed: bool = False
    # Serialized setup draft for crash-recovery only.
    wizard_in_progress_state: str = ""
    start_on_launch: bool = False

    # KDE compositor HDR controls for SDR content on HDR displays.
    compositor_hdr_mode: bool = False
    sdr_white_reference_preset: str = "80"
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
    # Defaults to GRB for supported Nanoleaf USB strip hardware.
    output_channel_order: str = "grb"
    reverse_zones: bool = False
    calibration_model: str = "corner_anchored"
    corner_anchor_top_left: int = -1
    corner_anchor_top_right: int = -1
    corner_anchor_bottom_right: int = -1
    corner_anchor_bottom_left: int = -1

    # Latency diagnostics/checker policy and latest visible result.
    auto_latency_policy: str = "manual"
    latency_last_backend: str = ""
    latency_last_value_ms: float = 0.0
    latency_last_trigger: str = ""
    latency_last_timestamp: str = ""

    # Recovery policy
    max_consecutive_errors: int = 5
    reinit_backoff_ms: int = 500

    # Logging / misc
    status_log_interval_s: float = 5.0
    verbose: bool = False

    def effective_calibration(self) -> CalibrationConfig:
        """Return the canonical calibration snapshot for runtime/UI consumers."""
        calibration = self.calibration or CalibrationConfig()
        return CalibrationConfig(
            schema_version=int(
                getattr(self, "calibration_schema_version", getattr(calibration, "schema_version", 1)) or 1
            ),
            calibration_schema_version=int(
                getattr(self, "calibration_schema_version", getattr(calibration, "calibration_schema_version", 1))
                or 1
            ),
            calibration_model=str(getattr(calibration, "calibration_model", "corner_anchored") or "corner_anchored"),
            device_zone_count=int(getattr(calibration, "device_zone_count", 0)),
            output_channel_order=str(getattr(calibration, "output_channel_order", "grb") or "grb"),
            normalized_reverse_zones=bool(getattr(calibration, "normalized_reverse_zones", False)),
            normalized_corner_anchors=[int(i) for i in (getattr(calibration, "normalized_corner_anchors", []) or [])],
            reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
            corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
            corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
            corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
            corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        )
