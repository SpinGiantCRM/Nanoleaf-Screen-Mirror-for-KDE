from __future__ import annotations

from dataclasses import dataclass, field

# Safety cap for manually configured physical strip zones. 512 is far above the
# supported single Nanoleaf USB Edge Strip sizes while keeping generated HID
# color payloads bounded if a config file is edited incorrectly.
MAX_DEVICE_ZONE_COUNT = 512


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
class LedCalibrationProfile:
    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    led_gamma: float = 1.0
    white_balance_temperature: float = 0.0
    chroma_compression: float = 0.0
    neutral_luminance_gain: float = 1.0
    black_luminance_cutoff: float = 0.0032
    black_luminance_knee: float = 0.0024
    color_matrix: list[float] = field(default_factory=list)


@dataclass
class AppConfig:
    # Config schema version for future migrations.
    schema_version: int = 1
    # Capture
    fps: int = 60
    # Auto keeps kwin-dbus as the KDE primary backend; other backends remain explicit
    # diagnostics/benchmark options.
    prefer_backend: str = "auto"

    # Color -> device mapping
    brightness: float = 1.0  # [0.0, 1.0]
    smoothing: float = 0.5  # One-Euro minimum responsiveness in [0.0, 1.0]
    smoothing_speed: float = (
        0.75  # Adaptive motion gain in [0.0, 4.0]; lower = slower response / more smoothing.
    )
    led_gamma: float = 1.0  # Output correction for LED electrical response.
    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    white_balance_temperature: float = 0.0  # Cool/warm tint bias in [-1, 1].
    chroma_compression: float = 0.0
    neutral_luminance_gain: float = 1.0
    black_luminance_cutoff: float = 0.0032
    black_luminance_knee: float = 0.0024
    led_calibration_profile_sdr: LedCalibrationProfile = field(
        default_factory=LedCalibrationProfile
    )
    led_calibration_profile_hdr: LedCalibrationProfile = field(
        default_factory=LedCalibrationProfile
    )

    # Zones
    zones: list[ZoneConfig] = field(default_factory=list)
    # If zones is empty, runtime derives zones from strip zone count + preset.
    # With the "horizontal" preset and count=1, this becomes a full-screen zone.
    # With the "edge-weighted" preset, make_edge_weighted_zones keeps edge strips.
    # Zone sampling stride (1 = every pixel, 2 = every other pixel, etc.).
    # Larger values reduce CPU cost at the expense of color precision.
    zone_sampling_stride: int = 1
    # Zone sampling engine:
    # - auto: choose the faster proven path for the active frame/zone shape
    # - legacy: pre-optimisation direct RGB integral sampling
    # - optimized: Oklab integral sampling path
    zone_sampling_engine: str = "auto"
    # New preset architecture (canonical model).
    layout_preset: str = "edge_strip"
    edge_locality: str = "balanced"
    light_spread: str = "balanced"
    sampling_quality: str = "balanced"
    performance_profile: str = "balanced"
    sampling_mode: str = "auto"
    motion_preset: str = "responsive"
    sync_mode: str = "standard"
    predictive_sync_strength: float = 0.35
    color_style: str = "ambient"
    layout_inset: float = 0.0
    layout_scale: float = 1.0
    letterbox_detection: bool = True
    drm_zone_patch_capture: bool = False
    # Empty string mirrors Plasma primary; set a KWin output name for another display.
    capture_monitor: str = ""
    # Persisted top/right/bottom/left source zone counts for corner-anchor mapping.
    source_side_counts: list[int] = field(default_factory=list)
    display_preset: str = "hdr"
    # Tracks whether the first-run display configurator has been completed.
    wizard_completed: bool = False
    # Schema version for wizard_in_progress_state JSON payload.
    wizard_state_version: int = 1
    # Serialized setup draft for crash-recovery only.
    wizard_in_progress_state: str = ""
    start_on_launch: bool = False
    # Whether the driver should auto-turn-on the device when syncing.
    auto_turn_on: bool = True

    # KDE compositor HDR controls for SDR content on HDR displays.
    compositor_hdr_mode: bool = False
    sdr_white_reference_preset: str = "80"
    # Plasma SDR white reference in nits (80 = no compositor SDR boost).
    sdr_boost_nits: float = 80.0

    # USB / device
    device_vid: int = 0x37FA
    device_pid: int = 0x8202
    allow_custom_device_ids: bool = False

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

    # Display gamut / ICC profile support.
    # - auto: detect from colord or EDID; fall back to sRGB
    # - srgb: force sRGB primaries
    # - dci-p3: DCI-P3 primaries
    # - bt.2020: BT.2020 primaries
    # - custom: user-provided chromaticities (not yet wired)
    display_gamut: str = "auto"
    custom_gamut_red_x: float = 0.6400
    custom_gamut_red_y: float = 0.3300
    custom_gamut_green_x: float = 0.3000
    custom_gamut_green_y: float = 0.6000
    custom_gamut_blue_x: float = 0.1500
    custom_gamut_blue_y: float = 0.0600
    accuracy_mode: bool = False
    live_diagnostics_enabled: bool = False

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
    # Optional process scheduling niceness preference.
    # normal: no niceness change
    # high: best-effort attempt to set nice=-5
    # very_high_experimental: best-effort attempt to set nice=-10
    performance_priority: str = "normal"
    # Pipeline: use the legacy single-threaded path instead of the 3-stage pipeline.
    # The 3-stage pipeline (capture → process → HID) is the default.
    use_legacy_pipeline: bool = False
    # Maximum seconds to wait for the first frame on startup before timing out.
    # Increase if kwin-dbus authorization is slow (e.g. first launch from terminal).
    startup_frame_timeout_s: float = 5.0
    # Drop processed frames older than max(min_max_send_age_ms, frame_budget * multiplier).
    stale_frame_drop_enabled: bool = True
    max_send_age_frame_budget_multiplier: float = 2.0
    min_max_send_age_ms: float = 60.0
    # Permit configured strip zone count to override USB-reported count (shows warning).
    allow_zone_count_override: bool = False

    def __post_init__(self) -> None:
        """Sync calibration field to ensure single source of truth.

        When ``calibration`` exists with default-zero values but top-level
        fields carry user data, populate ``calibration`` from top-level fields
        so ``effective_calibration()`` remains the canonical accessor.
        """
        cal = self.calibration
        if cal.device_zone_count <= 0 and self.device_zone_count > 0:
            cal.device_zone_count = self.device_zone_count
        if cal.output_channel_order == "grb" and self.output_channel_order != "grb":
            cal.output_channel_order = self.output_channel_order
        if not cal.reverse_zones and self.reverse_zones:
            cal.reverse_zones = self.reverse_zones
        if (
            cal.calibration_model == "corner_anchored"
            and self.calibration_model != "corner_anchored"
        ):
            cal.calibration_model = self.calibration_model
        if cal.corner_anchor_top_left < 0 and self.corner_anchor_top_left >= 0:
            cal.corner_anchor_top_left = self.corner_anchor_top_left
        if cal.corner_anchor_top_right < 0 and self.corner_anchor_top_right >= 0:
            cal.corner_anchor_top_right = self.corner_anchor_top_right
        if cal.corner_anchor_bottom_right < 0 and self.corner_anchor_bottom_right >= 0:
            cal.corner_anchor_bottom_right = self.corner_anchor_bottom_right
        if cal.corner_anchor_bottom_left < 0 and self.corner_anchor_bottom_left >= 0:
            cal.corner_anchor_bottom_left = self.corner_anchor_bottom_left

    def effective_calibration(self) -> CalibrationConfig:
        """Return the canonical calibration snapshot for runtime/UI consumers."""
        calibration = self.calibration or CalibrationConfig()
        return CalibrationConfig(
            schema_version=int(
                getattr(
                    self, "calibration_schema_version", getattr(calibration, "schema_version", 1)
                )
                or 1
            ),
            calibration_schema_version=int(
                getattr(
                    self,
                    "calibration_schema_version",
                    getattr(calibration, "calibration_schema_version", 1),
                )
                or 1
            ),
            calibration_model=str(
                getattr(calibration, "calibration_model", "corner_anchored") or "corner_anchored"
            ),
            device_zone_count=int(getattr(calibration, "device_zone_count", 0)),
            output_channel_order=str(getattr(calibration, "output_channel_order", "grb") or "grb"),
            normalized_reverse_zones=bool(getattr(calibration, "normalized_reverse_zones", False)),
            normalized_corner_anchors=[
                int(i) for i in (getattr(calibration, "normalized_corner_anchors", []) or [])
            ],
            reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
            corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
            corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
            corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
            corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        )


# Display gamut named constants (match values persisted in config).
GAMUT_AUTO: str = "auto"
GAMUT_SRGB: str = "srgb"
GAMUT_DCIP3: str = "dci-p3"
GAMUT_BT2020: str = "bt.2020"
GAMUT_CUSTOM: str = "custom"
