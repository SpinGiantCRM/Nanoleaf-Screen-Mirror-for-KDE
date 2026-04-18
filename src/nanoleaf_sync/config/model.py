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
    # Recovery scope: one real capture path (kwin-dbus) plus mock capture for setup/testing.
    prefer_backend: str = "kwin-dbus"

    # Color -> device mapping
    brightness: float = 1.0  # [0.0, 1.0]
    smoothing: float = 0.5  # EMA alpha in [0.0, 1.0]; higher = less smoothing

    # Zones
    zones: List[ZoneConfig] = field(default_factory=list)
    # If zones is empty, the service will use a default single full-screen zone.
    # Zone sampling stride (1 = every pixel, 2 = every other pixel, etc.).
    # Larger values reduce CPU cost at the expense of color precision.
    zone_sampling_stride: int = 1

    # USB / device
    device_vid: int = 0x0
    device_pid: int = 0x0
    # Default to mock device so the app runs without requiring HID hardware/protocol.
    use_mock_device: bool = True

    # Capture backend (development/demo).
    # Default to mock capture so the full pipeline can be tested immediately
    # even before DRM/KWin capture bindings are implemented.
    use_mock_capture: bool = False

    # Device zone calibration (mapping sampled screen zones to physical strip zones)
    # If 0, the service uses `len(zones)` (or 1 if zones are empty).
    device_zone_count: int = 0
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
