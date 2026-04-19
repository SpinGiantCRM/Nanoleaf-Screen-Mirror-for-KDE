from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


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
    smoothing_speed: float = 0.75  # One-Euro speed coefficient in [0.0, 4.0]
    led_gamma: float = 2.2  # Output correction for LED electrical response.

    # Zones
    zones: List[ZoneConfig] = field(default_factory=list)
    # If zones is empty, the service will use a default single full-screen zone.
    # Zone sampling stride (1 = every pixel, 2 = every other pixel, etc.).
    # Larger values reduce CPU cost at the expense of color precision.
    zone_sampling_stride: int = 1
    zone_preset: str = "edge-weighted"
    color_mode: str = "balanced"
    start_on_launch: bool = False

    # USB / device
    device_vid: int = 0x37FA
    device_pid: int = 0x8202

    # Capture backend toggle.
    # Default to real capture (kwin-dbus) for KDE Plasma; set True for diagnostics mode.
    use_mock_capture: bool = False

    # HDR conversion controls (used by HDR-capable capture paths / metadata-aware conversion).
    hdr_max_nits: float = 1000.0
    hdr_transfer: str = "srgb"
    hdr_primaries: str = "bt709"

    # Device zone calibration (mapping sampled screen zones to physical strip zones)
    # If `device_zone_count` is 0, runtime auto-mapping prefers detected device strip length.
    # Fallback is source zone count (`len(zones)`, or 1 if zones are empty).
    device_zone_count: int = 0
    # Physical channel order expected by the LED strip controller.
    # Defaults to GRB for currently supported Nanoleaf USB strip hardware.
    output_channel_order: str = "grb"
    zone_offset: int = 0
    reverse_zones: bool = False
    # Optional explicit mapping: list of screen-zone indices for each device zone.
    # If non-empty, it takes precedence over `zone_offset`/`reverse_zones`.
    explicit_zone_map: List[int] = field(default_factory=list)

    # Recovery policy
    max_consecutive_errors: int = 5
    reinit_backoff_ms: int = 500

    # Logging / misc
    status_log_interval_s: float = 5.0
    verbose: bool = False
