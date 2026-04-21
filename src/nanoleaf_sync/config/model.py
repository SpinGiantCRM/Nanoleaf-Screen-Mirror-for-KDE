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

    # Recovery policy
    max_consecutive_errors: int = 5
    reinit_backoff_ms: int = 500

    # Logging / misc
    status_log_interval_s: float = 5.0
    verbose: bool = False
